from flask import Flask, request, render_template, redirect, url_for, jsonify, session, Response, send_file
import requests
import openai
from openai import OpenAI
from collections import defaultdict
import time
import app_helper
import boto3
from botocore.exceptions import NoCredentialsError
from authlib.integrations.flask_client import OAuth
from functools import wraps
import os
import subprocess  # To use wget or curl

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Configure OAuth
oauth = OAuth(app)
oauth.register(
    name='google',
    client_id='683065076829-2c9f6jf7vi4krv0rfrjntderrqga68j7.apps.googleusercontent.com',
    client_secret='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',
    authorize_params=None,
    access_token_params=None,
    refresh_token_url=None,
    redirect_uri='http://127.0.0.1:5000/auth',
    client_kwargs={'scope': 'openid profile email'},
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
)

# Set your OpenAI API key here
openai.api_key = 'sk-proj-kHoXD3aKcluuSADuVNZBT3BlbkFJVFiHGTt0BRah1ra9ZGql'

metriport_api_key = 'NzNCSTZuS0ZQalVoT2pmX0tfb1laOjE3Mzg4Y2Q4LTUwOGMtNDU1ZC04YzA4LWI3MjQwMzU0YTBkYg'
API_URL = "https://api.sandbox.metriport.com/medical/v1/patient/{}/consolidated"
DOCUMENT_URL_API = "https://api.sandbox.metriport.com/medical/v1/document/download-url?fileName={}"

client = OpenAI(api_key=openai.api_key)

# AWS S3 setup
aws_access_key_id = 'AKIA2ES25DXDJPSZ3S5Z'
aws_secret_access_key = '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'
aws_region = 'us-west-2'

s3 = boto3.client(
    's3',
    aws_access_key_id=aws_access_key_id,
    aws_secret_access_key=aws_secret_access_key,
    region_name=aws_region
)

main_bucket_name = "sofdoc-autoprep"

def save_summary_to_s3(user_email, patient_name, file_name, summary):
    user_bucket_prefix = f"{user_email.replace('@', '-').replace('.', '-')}"
    patient_key_prefix = f"{user_bucket_prefix}/{patient_name.replace(' ', '-').lower()}"
    object_key = f"{patient_key_prefix}/{file_name}"
    
    s3.put_object(Bucket=main_bucket_name, Key=object_key, Body=summary, ContentType='text/html')
    print(f"Uploaded summary to S3: {object_key}")

def save_documents_to_s3(user_email, patient_name, documents):
    user_bucket_prefix = f"{user_email.replace('@', '-').replace('.', '-')}"
    patient_prefix = f"{user_bucket_prefix}/{patient_name.replace(' ', '-').lower()}/Documents/"
    
    for document in documents:
        try:
            with open(document['path'], 'rb') as doc_file:
                # Upload to S3 using the same name as it was saved locally
                file_path = f"{patient_prefix}{os.path.basename(document['path'])}"
                s3.put_object(Bucket=main_bucket_name, Key=file_path, Body=doc_file)
                print(f"Successfully uploaded document to S3: {file_path}")
            os.remove(document['path'])  # Clean up local file after upload
        except Exception as e:
            print(f"Failed to upload document: {document['path']} to S3 due to {str(e)}")


def list_documents_from_s3(user_email, patient_name):
    user_bucket_prefix = f"{user_email.replace('@', '-').replace('.', '-')}"
    patient_prefix = f"{user_bucket_prefix}/{patient_name.replace(' ', '-').lower()}/Documents/"
    
    response = s3.list_objects_v2(Bucket=main_bucket_name, Prefix=patient_prefix)
    documents = response.get('Contents', [])
    print(f"Found documents in S3: {[doc['Key'] for doc in documents]}")
    return [doc['Key'].split('/')[-1] for doc in documents]

def list_patients_from_s3(user_email):
    user_bucket_prefix = f"{user_email.replace('@', '-').replace('.', '-')}"
    response = s3.list_objects_v2(Bucket=main_bucket_name, Prefix=user_bucket_prefix + '/', Delimiter='/')
    
    folders = [content.get('Prefix').split('/')[-2] for content in response.get('CommonPrefixes', [])]
    sorted_folders = sorted(folders, key=lambda x: s3.head_object(Bucket=main_bucket_name, Key=f"{user_bucket_prefix}/{x}/main_summary.html")['LastModified'], reverse=True)
    
    patients_dates = [s3.head_object(Bucket=main_bucket_name, Key=f"{user_bucket_prefix}/{x}/main_summary.html")['LastModified'] for x in sorted_folders]
    
    return sorted_folders[:10] if len(sorted_folders) > 10 else sorted_folders, patients_dates

def list_summaries_from_s3(user_email, patient_name):
    user_bucket_prefix = f"{user_email.replace('@', '-').replace('.', '-')}"
    patient_key_prefix = f"{user_bucket_prefix}/{patient_name.replace(' ', '-').lower()}"
    
    response = s3.list_objects_v2(Bucket=main_bucket_name, Prefix=patient_key_prefix)
    files = response.get('Contents', [])
    return files

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def index():
    if 'user' in session:
        return redirect(url_for('home'))
    return render_template('index.html')

@app.route('/home')
@login_required
def home():
    return render_template('home.html')

@app.route('/add-patient', methods=['GET', 'POST'])
@login_required
def add_patient():
    if request.method == 'POST':
        patient = {
            'first_name': request.form['first_name'],
            'last_name': request.form['last_name'],
            'dob': request.form['dob'],
            'gender': request.form['gender'],
            'address': request.form['address'],
            'patient_id': request.form['patient_id']
        }
        patient_full_name = f"{patient['first_name']} {patient['last_name']}"
        
        headers = {
            'x-api-key': metriport_api_key
        }
        response = requests.get(API_URL.format(patient['patient_id']), headers=headers)
        if response.status_code == 200:
            patient_history = response.json()
            # Extract and download documents
            documents = get_patient_documents(patient_history)
            if documents:
                save_documents_to_s3(session['user']['email'], patient_full_name, documents)
            else:
                print(f"No documents found for patient {patient_full_name}.")

            summarized_history, final_summary = parse_patient_history(patient_history)

            # Clean the final summary before saving
            cleaned_final_summary = clean_html(final_summary)

            # Save the main summary
            save_summary_to_s3(session['user']['email'], patient_full_name, "main_summary.html", cleaned_final_summary)

            # Clean and combine medication summaries before saving
            medications_summary = ""
            if "MedicationRequest" in summarized_history:
                medications_summary += clean_html(summarized_history["MedicationRequest"])
            if "MedicationAdministration" in summarized_history:
                medications_summary += clean_html(summarized_history["MedicationAdministration"])
            
            if medications_summary:
                save_summary_to_s3(session['user']['email'], patient_full_name, "Medications_summary.html", medications_summary)

            # Clean and save other individual resource summaries, excluding medications
            for resource_type, summary in summarized_history.items():
                if resource_type not in ["Patient", "Practitioner", "MedicationRequest", "MedicationAdministration"]:
                    cleaned_summary = clean_html(summary)
                    file_name = f"{resource_type}_summary.html"
                    save_summary_to_s3(session['user']['email'], patient_full_name, file_name, cleaned_summary)

        return redirect(url_for('add_patient', success=True))
    return render_template('add_patient.html')

def clean_html(content):
    """Remove unnecessary characters or text from HTML content."""
    return content.strip('`').replace('html', '', 1).strip()

import os

def get_patient_documents(patient_history):
    documents = []
    existing_files = set()  # To keep track of filenames to avoid duplicates

    for entry in patient_history.get('entry', []):
        resource = entry.get('resource', {})
        print(f"Processing resourceType: {resource.get('resourceType')}")

        if resource.get('resourceType') == 'DocumentReference':
            description = resource.get('description', 'Unknown Document')
            print(f"Found DocumentReference with description: {description}")

            for content in resource.get('content', []):
                attachment = content.get('attachment', {})
                title = attachment.get('title')
                if title:
                    # Extract the file extension from the title
                    extension = os.path.splitext(title)[1]
                    base_name = f"{description}{extension}"

                    # Check if the file already exists, and if so, append a number in brackets
                    file_name = base_name
                    counter = 1
                    while file_name in existing_files or os.path.exists(os.path.join(os.getcwd(), file_name)):
                        file_name = f"{description}({counter}){extension}"
                        counter += 1

                    existing_files.add(file_name)
                    file_path = os.path.join(os.getcwd(), file_name)  # Download to the current working directory
                    print(f"Downloading document as: {file_name}")

                    download_url_response = requests.get(DOCUMENT_URL_API.format(title), headers={'x-api-key': metriport_api_key})
                    if download_url_response.status_code == 200:
                        download_url = download_url_response.json().get('url')

                        # Download the file using requests
                        try:
                            with requests.get(download_url, stream=True) as r:
                                r.raise_for_status()
                                with open(file_path, 'wb') as f:
                                    for chunk in r.iter_content(chunk_size=8192):
                                        f.write(chunk)
                            print(f"Downloaded document: {file_name} to {file_path}")
                            documents.append({
                                'path': file_path,
                                'description': description
                            })
                        except Exception as e:
                            print(f"Failed to download document: {title} due to {str(e)}")
                    else:
                        print(f"Failed to retrieve download URL for document: {title} with status code {download_url_response.status_code}")
                else:
                    print("No title found for this document.")
        else:
            print(f"Skipping resourceType: {resource.get('resourceType')}")
    return documents


@app.route('/view-summaries', methods=['GET', 'POST'])
@login_required
def view_summaries():
    patient_name = request.args.get('patient_name')
    
    if not patient_name:
        patients, patients_dates = list_patients_from_s3(session['user']['email'])
        patient_data = list(zip(patients, patients_dates))
        return render_template('view_summaries.html', patient_data=patient_data, selected_patient=None, summaries=[], patient_name=None)

    summaries = list_summaries_from_s3(session['user']['email'], patient_name)
    documents = list_documents_from_s3(session['user']['email'], patient_name)
    
    if not summaries:
        return render_template('view_summaries.html', patient_data=[], selected_patient=None, summaries=[], documents=[], patient_name=patient_name, message="No summaries to display.")

    summary_contents = []
    medications_summary = ""

    for summary in summaries:
        summary_obj = s3.get_object(Bucket=main_bucket_name, Key=summary['Key'])
        
        # Check if the file is a text-based summary or a binary document
        content_type = summary_obj.get('ContentType')
        
        if content_type == 'text/html' or content_type == 'text/plain':
            summary_content = summary_obj['Body'].read().decode('utf-8')
            if summary['Key'].endswith('MedicationRequest_summary.html') or summary['Key'].endswith('MedicationAdministration_summary.html'):
                medications_summary += summary_content
            else:
                summary_contents.append({
                    'Key': summary['Key'],
                    'Content': summary_content
                })
        else:
            print(f"Skipping non-text file: {summary['Key']} with content type: {content_type}")

    # Add the merged Medications summary
    if medications_summary:
        summary_contents.append({
            'Key': 'Medications_summary.html',
            'Content': medications_summary
        })

    return render_template('view_summaries.html', patient_data=[], selected_patient=patient_name, summaries=summary_contents, documents=documents)

@app.route('/get-latest-patients')
@login_required
def get_latest_patients():
    patients, patients_dates = list_patients_from_s3(session['user']['email'])
    patient_list = [
        {
            'name': patient,
            'date': str(date)
        } for patient, date in zip(patients, patients_dates)
    ]
    return jsonify(patient_list)

@app.route('/get-latest-summaries')
@login_required
def get_latest_summaries():
    patient_name = request.args.get('patient_name')
    summaries = list_summaries_from_s3(session['user']['email'], patient_name)
    summaries_list = [
        {
            'Key': summary['Key'].split('/')[-1],
            'LastModified': summary['LastModified']
        } for summary in summaries
    ]
    return jsonify(summaries_list)

@app.route('/view-document/<patient_name>/<document_name>')
@login_required
def view_document(patient_name, document_name):
    user_bucket_prefix = f"{session['user']['email'].replace('@', '-').replace('.', '-')}"
    document_key = f"{user_bucket_prefix}/{patient_name.replace(' ', '-').lower()}/Documents/{document_name}"

    try:
        document_obj = s3.get_object(Bucket=main_bucket_name, Key=document_key)
        file_content = document_obj['Body'].read()

        return Response(file_content, mimetype='application/octet-stream',
                        headers={"Content-Disposition": f"inline;filename={document_name}"})
    except Exception as e:
        print(f"Error fetching document {document_name} from S3: {str(e)}")
        return "Error retrieving document", 500

@app.route('/download-document/<patient_name>/<document_name>')
@login_required
def download_document(patient_name, document_name):
    user_bucket_prefix = f"{session['user']['email'].replace('@', '-').replace('.', '-')}"
    document_key = f"{user_bucket_prefix}/{patient_name.replace(' ', '-').lower()}/Documents/{document_name}"

    try:
        document_obj = s3.get_object(Bucket=main_bucket_name, Key=document_key)
        file_content = document_obj['Body'].read()

        return Response(file_content, mimetype='application/octet-stream',
                        headers={"Content-Disposition": f"attachment;filename={document_name}"})
    except Exception as e:
        print(f"Error fetching document {document_name} from S3: {str(e)}")
        return "Error retrieving document", 500

@app.route('/login')
def login():
    redirect_uri = url_for('auth', _external=True)
    return oauth.google.authorize_redirect(redirect_uri)

@app.route('/auth')
def auth():
    token = oauth.google.authorize_access_token()
    session['user'] = token['userinfo']
    return redirect('/home')

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect('/')

@app.route('/profile')
@login_required
def profile():
    user = session.get('user')
    return jsonify(user)

def parse_patient_history(patient_history, summarize=True):
    result = defaultdict(list)

    for entry in patient_history.get('entry', []):
        resource = entry.get('resource', {})
        resource_type = resource.get('resourceType')
        if resource_type:
            result[resource_type].append(resource)
    if not summarize:
        return ""

    summarized_history = {}
    all_summaries = []
    max_words = 200

    if "Patient" in result:
        content = app_helper.formatter(result["Patient"])
        summary = app_helper.get_gpt_response(client, f"Summarize the following medical information in no more than {max_words} words. Provide the summary in bullet points in an HTML format, highlighting the concerning trends in red.:\n\n{content}")
        summarized_history["Patient"] = summary
        all_summaries.append(summary)
        del result["Patient"]

    for resource_type, resources in result.items():
        if resource_type in ['DiagnosticReport', 'Patient', 'Practitioner']:
            continue 
        content = app_helper.formatter(resources)        
        summary = app_helper.get_gpt_response(client, f"Summarize the following medical information in no more than {max_words} words. Provide the summary in bullet points in an HTML format, highlighting the concerning trends in red.:\n\n{content}")
        summarized_history[resource_type] = summary
        all_summaries.append(summary)
    
    concatenated_summaries = " ".join(all_summaries)
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": f"Here is an example summary of a patient with knee injury: Patient has a history of knee pain after being hit by a ball playing cricket ball 2 years ago. 2 MRIs were taken a year apart, latest one showed mild fraying of meniscus and bone contusion in femur. He underwent 6 physiotherapy sessions across a year. \n Use this above template to provide a brief summary using bullet points for the medical information mentioned below in no more than 100 words. Provide the summary in an HTML format, highlighting the concerning trends in red. Here is the sample  medical information:\n\n: {concatenated_summaries}"}
        ],
        max_tokens=1024,
        temperature=0.0
    )
    ultimate_summary = response.choices[0].message.content.strip()
    
    return summarized_history, ultimate_summary

if __name__ == '__main__':
    app.run(debug=True)
