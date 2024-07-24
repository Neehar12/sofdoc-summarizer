import google.generativeai as genai
from google.generativeai.types import generation_types
import PIL.Image
import os
from flask import Flask, request, render_template, jsonify
import requests
import os
import json
from collections import defaultdict
import time
from mistralai.client import MistralClient
from mistralai.models.chat_completion import ChatMessage
import app_helper

app = Flask(__name__)

endpoint = "https://Mistral-large-uflfb-serverless.westus.inference.ai.azure.com"
api_key = "31hQdxiXtemCNk8jF7m9hCBeZcksIVfN"
model = "azureai"

client = MistralClient(api_key=api_key,
                       endpoint=endpoint)

# response = model.generate_content(["What is in this photo?", img])
# print(response.text)
# openai.api_key = 'sk-proj-JAeipb6Clq2dLjB8JOePT3BlbkFJd1QYzUtRW7Kv3t2WBo0I'
metriport_api_key = 'NzNCSTZuS0ZQalVoT2pmX0tfb1laOjE3Mzg4Y2Q4LTUwOGMtNDU1ZC04YzA4LWI3MjQwMzU0YTBkYg'
API_URL = "https://api.sandbox.metriport.com/medical/v1/patient/019085d7-34f3-7392-9cff-c52f2a43a288/consolidated"

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

def parse_patient_history(patient_history):
    result = defaultdict(list)
    total_tokens = 0

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
        content = app_helper.formatter(resources)
        if resource_type == "Observation":
            summary = summarize_content(content, max_chunk_size=40000)
        elif resource_type == "Procedure":
            summary = summarize_content(content)
        else:
            summary = summarize_content(content)
        summarized_history[resource_type] = summary
        if resource_type != "Patient":
            all_summaries.append(summary)
    
    # Create a final summary using all the individual summaries
    concatenated_summaries = " ".join(all_summaries)
    final_summary = summarize_content(concatenated_summaries, summary_only=True)
    
    config = genai.GenerationConfig(
        max_output_tokens=4000, temperature=0, 
    )

    # Generate text
    # response = model.generate_content(
    #     [f"You are a physician assistant workiing at a hospital. You are reporting to an MD, who is a primary care provider. Your job is to give the patients' medical summary to the MD. Here is an example summary of a patient with knee injury in the quotes: \"Patient has a history of knee pain after being hit by a ball playing cricket ball 2 years ago. 2 MRIs were taken a year apart, latest one showed mild fraying of meniscus and bone contusion in femur. He underwent 6 physiotherapy sessions across a year.\" \n Now make a summary for the following patient data, given that you are a physician assistant in less than 50 words: {final_summary}"], generation_config=config
    # )

    
    message=f"You are a physician assistant workiing at a hospital. You are reporting to an MD, who is a primary care provider. Your job is to give the patients' medical summary to the MD. Here is an example summary of a patient with knee injury in the quotes: \"Patient has a history of knee pain after being hit by a ball playing cricket ball 2 years ago. 2 MRIs were taken a year apart, latest one showed mild fraying of meniscus and bone contusion in femur. He underwent 6 physiotherapy sessions across a year.\" \n Now make a summary for the following patient data, given that you are a physician assistant in less than 50 words: {final_summary}"
    (response, token) = app_helper.get_mistral_response(client, message)
    total_tokens += token
    ultimate_summary = response.strip()

    print(total_tokens)
    
    return summarized_history, ultimate_summary

def summarize_content(content, max_chunk_size=40000, max_words=500, summary_only=False):
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
            # response = openai.ChatCompletion.create(
            #     model="gpt-3.5-turbo",
            #     messages=[
            #         {"role": "system", "content": "You are a helpful assistant specialized in summarizing medical information."},
            #         {"role": "user", "content": f"Summarize the following medical information in no more than {max_words} words and highlight concerning trends:\n\n{chunk_with_previous_summary}"}
            #     ],
            #     max_tokens=4000
            # )
            # config = genai.GenerationConfig(
            #     max_output_tokens=4000, temperature=0
            # )

            # # Generate text
            # response = model.generate_content(
            #     [f"Summarize the following medical information in no more than {max_words} words and highlight concerning trends:\n\n{chunk_with_previous_summary}"], generation_config=config
            # )

            # With streaming 
            
            message=f"Summarize the following medical information in no more than {max_words} words and highlight concerning trends:\n\n{chunk_with_previous_summary}"      
            (response, token) = app_helper.get_mistral_response(client, message)
            total_tokens += token
            previous_summary = response.strip()
            # time.sleep(sleep_time) #needs to be optimized
            
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