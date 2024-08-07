from flask import Flask, request, render_template, redirect, url_for, jsonify, session
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
    redirect_uri='http://127.0.0.1:5000/auth',  # Change to your redirect URI
    client_kwargs={'scope': 'openid profile email'},
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
)

# Set your OpenAI API key here
openai.api_key = 'sk-proj-kHoXD3aKcluuSADuVNZBT3BlbkFJVFiHGTt0BRah1ra9ZGql'

metriport_api_key = 'NzNCSTZuS0ZQalVoT2pmX0tfb1laOjE3Mzg4Y2Q4LTUwOGMtNDU1ZC04YzA4LWI3MjQwMzU0YTBkYg'
API_URL = "https://api.sandbox.metriport.com/medical/v1/patient/{}/consolidated"
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

def create_bucket_if_not_exists(bucket_name):
    try:
        s3.head_bucket(Bucket=bucket_name)
    except:
        s3.create_bucket(Bucket=bucket_name, CreateBucketConfiguration={'LocationConstraint': aws_region})

def save_summary_to_s3(user_email, patient_name, summary):
    user_bucket_prefix = f"{user_email.replace('@', '-').replace('.', '-')}"
    create_bucket_if_not_exists(main_bucket_name)
    file_name = f"{patient_name}.txt"
    s3.put_object(Bucket=main_bucket_name, Key=f"{user_bucket_prefix}/{file_name}", Body=summary)

def list_summaries_from_s3(user_email):
    user_bucket_prefix = f"{user_email.replace('@', '-').replace('.', '-')}"
    create_bucket_if_not_exists(main_bucket_name)
    response = s3.list_objects_v2(Bucket=main_bucket_name, Prefix=user_bucket_prefix)
    files = response.get('Contents', [])
    sorted_files = sorted(files, key=lambda x: x['LastModified'], reverse=True)
    return sorted_files[:5] if len(sorted_files) > 5 else sorted_files

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
            _, final_summary = parse_patient_history(patient_history)
            save_summary_to_s3(session['user']['email'], patient_full_name, final_summary)
        
        return redirect(url_for('add_patient', success=True))
    return render_template('add_patient.html')

@app.route('/view-summaries', methods=['GET', 'POST'])
@login_required
def view_summaries():
    summaries = list_summaries_from_s3(session['user']['email'])
    selected_summary = None
    if request.method == 'POST':
        file_name = request.form['file_name']
        user_bucket_prefix = f"{session['user']['email'].replace('@', '-').replace('.', '-')}"
        summary_obj = s3.get_object(Bucket=main_bucket_name, Key=f"{user_bucket_prefix}/{file_name}")
        selected_summary = summary_obj['Body'].read().decode('utf-8')
    return render_template('view_summaries.html', summaries=summaries, selected_summary=selected_summary)

@app.route('/get-latest-summaries')
@login_required
def get_latest_summaries():
    summaries = list_summaries_from_s3(session['user']['email'])
    summaries_list = [
        {
            'Key': summary['Key'].split('/')[-1],
            'LastModified': summary['LastModified']
        } for summary in summaries
    ]
    return jsonify(summaries_list)

@app.route('/login')
def login():
    redirect_uri = url_for('auth', _external=True)
    return oauth.google.authorize_redirect(redirect_uri)

@app.route('/auth')
def auth():
    token = oauth.google.authorize_access_token()
    print(token)
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
        summary = app_helper.get_gpt_response(client, f"Summarize the following medical information in no more than {max_words} words and highlight concerning trends:\n\n{content}")
        summarized_history["Patient"] = summary
        all_summaries.append(summary)
        del result["Patient"]

    for resource_type, resources in result.items():
        if resource_type == 'DiagnosticReport' or resource_type == 'Patient':
            continue 
        content = app_helper.formatter(resources)        
        summary = app_helper.get_gpt_response(client, f"Summarize the following medical information in no more than {max_words} words and highlight concerning trends:\n\n{content}")
        summarized_history[resource_type] = summary
        all_summaries.append(summary)
    
    concatenated_summaries = " ".join(all_summaries)
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": f"Here is an example summary of a patient with knee injury: Patient has a history of knee pain after being hit by a ball playing cricket ball 2 years ago. 2 MRIs were taken a year apart, latest one showed mild fraying of meniscus and bone contusion in femur. He underwent 6 physiotherapy sessions across a year. \n Use this above template to provide a brief summary using bullet points for the following sample medical information in no more than 100 words and highlight concerning trends. Also, provide a brief summary of past visits from the following sample medical information in no more than 100 words and highlight concerning trends. Also Provide a brief summary of past medications from the following sample medical information in no more than 100 words and highlight concerning trends. Provide a brief summary of past test and examination results from the following sample medical information in no more than 100 words and highlight concerning trends. Here is the sample  medical information:\n\n: {concatenated_summaries}"}
        ],
        max_tokens=1024,
        temperature=0.0
    )
    ultimate_summary = response.choices[0].message.content.strip()
    
    return summarized_history, ultimate_summary

if __name__ == '__main__':
    app.run(debug=True)
