from flask import Flask, request, render_template, jsonify
import requests
import openai
from openai import OpenAI
from collections import defaultdict
import time
import app_helper

app = Flask(__name__)

# Set your OpenAI API key here
openai.api_key = 'sk-proj-JAeipb6Clq2dLjB8JOePT3BlbkFJd1QYzUtRW7Kv3t2WBo0I'

metriport_api_key = 'NzNCSTZuS0ZQalVoT2pmX0tfb1laOjE3Mzg4Y2Q4LTUwOGMtNDU1ZC04YzA4LWI3MjQwMzU0YTBkYg'
API_URL = "https://api.sandbox.metriport.com/medical/v1/patient/{}/consolidated"
client = OpenAI(api_key=openai.api_key)

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

def parse_patient_history(patient_history, summarize=True):
    result = defaultdict(list)

    for entry in patient_history.get('entry', []):
        resource = entry.get('resource', {})
        resource_type = resource.get('resourceType')
        if resource_type:
            result[resource_type].append(resource)
            resource_array.append(resource)
    if not summarize:
     return ""

    ##################################################################
    # Summarization (HIPAA Compliant post )

    summarized_history = {}
    all_summaries = []
    max_words = 200
    # Summarize "Patient" resource type first
    if "Patient" in result:
        content = app_helper.formatter(result["Patient"])
        summary = app_helper.get_gpt_response(client, f"Summarize the following medical information in no more than {max_words} words and highlight concerning trends:\n\n{content}")
        summarized_history["Patient"] = summary
        all_summaries.append(summary)
        del result["Patient"]

    print(result.keys())
    # Summarize the rest of the resource types
    for resource_type, resources in result.items():
        if  resource_type == 'DiagnosticReport' or resource_type == 'Patient':
            continue 
        content = app_helper.formatter(resources)        
        summary = app_helper.get_gpt_response(client, f"Summarize the following medical information in no more than {max_words} words and highlight concerning trends:\n\n{content}")
        summarized_history[resource_type] = summary
        all_summaries.append(summary)
    
    # Create a final summary using all the individual summaries
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
    print('prompt_tokens:' + str(response.usage.prompt_tokens) + ', completion_tokens:' + str(response.usage.completion_tokens))
    ultimate_summary = response.choices[0].message.content.strip()
    
    return summarized_history, ultimate_summary


if __name__ == '__main__':
    app.run(debug=True)