from flask import Flask, request, render_template, jsonify
import requests
import openai
import os
import json
from collections import defaultdict
import time

app = Flask(__name__)

# Set your OpenAI API key here
openai.api_key = 'sk-proj-JAeipb6Clq2dLjB8JOePT3BlbkFJd1QYzUtRW7Kv3t2WBo0I'
metriport_api_key = 'NzNCSTZuS0ZQalVoT2pmX0tfb1laOjE3Mzg4Y2Q4LTUwOGMtNDU1ZC04YzA4LWI3MjQwMzU0YTBkYg'
API_URL = "https://api.sandbox.metriport.com/medical/v1/patient/{}/consolidated"

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        patient_id = request.form['patient_id']
        headers = {
            'x-api-key': metriport_api_key
        }
        response = requests.get(API_URL.format(patient_id), headers=headers)
        if response.status_code == 200:
            patient_history = response.json()
            parsed_history, final_summary = parse_patient_history(patient_history)
            return render_template('index.html', patient_history=parsed_history, final_summary=final_summary)
        else:
            error = f"Error: {response.status_code}, {response.text}"
            return render_template('index.html', error=error)
    return render_template('index.html')

def formatter(resources):
    output = ''
    num_output = 0
    for resource in resources:
        # print(resource)
        # print(resource.keys())
        resource.pop('meta')
        resource.pop('id')
        if 'subject' in resource.keys():
            resource.pop('subject')
        if '_status' in resource.keys():
            resource.pop('_status')
        if 'extension' in resource.keys():
           resource.pop('extension')
        if resource['resourceType'] == 'Observation':
            test_name = ''
            if 'category' in resource.keys():    
            for category in resource['category']:
                for coding in category['coding']:
                    test_name += '[' + coding['code'] + ']'
            resource.pop('category')
            if 'text' in resource['code'].keys():
                test_name += '[' + resource['code']['text'] + ']'
            for coding in resource['code']['coding']:
                test_name += '(' + coding['display'] + ':' + coding['code'] + ')'
            resource.pop('code')
            resource['testName'] = test_name
            resource['valueQuantity'] = str(resource['valueQuantity']['value']) + ' ' + resource['valueQuantity']['code'] + ' ('+resource['valueQuantity']['unit'] + ')' 
            # print(resource)
            # num_output += 1
            # if num_output > 5:
            #     break
            print(resource.keys())

    return "\n".join([str(resource) for resource in resources])

def parse_patient_history(patient_history):
    result = defaultdict(list)

    for entry in patient_history.get('entry', []):
        resource = entry.get('resource', {})
        resource_type = resource.get('resourceType')
        if resource_type:
            result[resource_type].append(resource)

    summarized_history = {}
    all_summaries = []
    
    # Summarize "Patient" resource type first
    if "Patient" in result:
        content = "\n".join([str(resource) for resource in result["Patient"]])
        summary = summarize_content(content)
        summarized_history["Patient"] = summary
        all_summaries.append(summary)
        del result["Patient"]
    
    # Summarize the rest of the resource types
    for resource_type, resources in result.items():
        if  resource_type == 'DiagnosticReport' or resource_type == 'Patient':
            continue 
        content = formatter(resources)
        if resource_type == "Observation":
            summary = summarize_content(content, max_chunk_size=30000, sleep_time=15)
        elif resource_type == "Procedure":
            summary = summarize_content(content, sleep_time=15)
        else:
            summary = summarize_content(content)
        summarized_history[resource_type] = summary
        if resource_type != "Patient":
            all_summaries.append(summary)
    
    # Create a final summary using all the individual summaries
    concatenated_summaries = " ".join(all_summaries)
    final_summary = summarize_content(concatenated_summaries, summary_only=True)
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": f"Here is an example summary of a patient with knee injury: Patient has a history of knee pain after being hit by a ball playing cricket ball 2 years ago. 2 MRIs were taken a year apart, latest one showed mild fraying of meniscus and bone contusion in femur. He underwent 6 physiotherapy sessions across a year. \n Use this above template to give the summary for the following patient medical history in no more than 150 words: {final_summary}"}
        ],
        max_tokens=512,
        temperature=0.0,
        top_p=0.9
    )
    ultimate_summary = response.choices[0].message.content.strip()
    
    return summarized_history, ultimate_summary

def summarize_content(content, max_chunk_size=20000, max_words=500, summary_only=False, sleep_time=10):
    try:
        # Split content into chunks if it exceeds the maximum chunk size
        chunks = []
        while len(content) > max_chunk_size and not summary_only:
            chunk = content[:max_chunk_size]
            last_newline = chunk.rfind('\n')
            if last_newline != -1:
                chunk = content[:last_newline]
            chunks.append(chunk)
            content = content[len(chunk):]
        chunks.append(content)

        # Summarize each chunk and keep only the summary of the last chunk
        previous_summary = ""
        for chunk in chunks:
            chunk_with_previous_summary = previous_summary + "\n" + chunk if previous_summary else chunk
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant specialized in summarizing medical information."},
                    {"role": "user", "content": f"Summarize the following medical information in no more than {max_words} words and highlight concerning trends:\n\n{chunk_with_previous_summary}"}
                ],
                max_tokens=4000
            )
            previous_summary = response.choices[0].message['content'].strip()
            time.sleep(sleep_time) #needs to be optimized
            
            # Ensure the summary is not more than max_words
            words = previous_summary.split()
            if len(words) > max_words:
                previous_summary = ' '.join(words[:max_words])
        
        # Return the summary of the last chunk
        return previous_summary
    except Exception as e:
        return f"Error in summarizing content: {str(e)}"

if __name__ == '__main__':
    app.run(debug=True)