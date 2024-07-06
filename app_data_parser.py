# from flask import Flask, request, render_template, jsonify
import requests
import openai
import os
import json
from collections import defaultdict

# app = Flask(__name__)

# Set your OpenAI API key here
openai.api_key = 'sk-proj-jO6omQzH5qvPTourak6jT3BlbkFJ5JWFTK8A0TUsmgoK6B2a'
metriport_api_key = 'NzNCSTZuS0ZQalVoT2pmX0tfb1laOjE3Mzg4Y2Q4LTUwOGMtNDU1ZC04YzA4LWI3MjQwMzU0YTBkYg'
API_URL = "https://api.sandbox.metriport.com/medical/v1/patient/0190527b-be0d-7ba3-9bcf-29d5997f92db/consolidated"


headers = {
    "x-api-key": metriport_api_key,
}

response = requests.get(API_URL, headers=headers)

print(response.status_code)
patient_history = response.json()

# def status_analyzer(resources):
    # distinct_status = set()
    # for resource in resources:
    #     # if resource['status'] == 'unknown':
    #         # print(resource)
    #     if '_status' in resource.keys(): 
    #         if resource['status'] +  resource['_status']['extension'][0]['valueCodeableConcept']['coding'][0]['code']  in distinct_status:
    #             continue
    #         else:
    #             distinct_status.add(resource['status'] +  resource['_status']['extension'][0]['valueCodeableConcept']['coding'][0]['code'])
    #     else:
    #         if resource['status'] in distinct_status:
    #             continue
    #         distinct_status.add(resource['status'])
    # print(distinct_status)


def formatter(resources):
    output = ''
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
            if 'code' in resource.keys() and 'unit' in resource.keys():
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

    print(result.keys())
    # return -1
    # Summarize the rest of the resource types
    for resource_type, resources in result.items():
        if  resource_type == 'DiagnosticReport':
            continue 
        content = formatter(resources)
        summary = summarize_content(content)
        summarized_history[resource_type] = summary
        all_summaries.append(summary)
    
    # Create a final summary using all the individual summaries
    concatenated_summaries = " ".join(all_summaries)
    final_summary = summarize_content(concatenated_summaries, max_words=100, summary_only=True)
    
    return summarized_history, final_summary

def summarize_content(content, max_chunk_size=30000, max_words=500, summary_only=False):
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
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant specialized in summarizing medical information."},
                    {"role": "user", "content": f"Summarize the following medical information in no more than {max_words} words:\n\n{chunk_with_previous_summary}"}
                ],
                max_tokens=150
            )
            previous_summary = response.choices[0].message['content'].strip()
            
            # Ensure the summary is not more than max_words
            words = previous_summary.split()
            if len(words) > max_words:
                previous_summary = ' '.join(words[:max_words])
        
        # Return the summary of the last chunk
        return previous_summary
    except Exception as e:
        return f"Error in summarizing content: {str(e)}"
    return ""


print(parse_patient_history(patient_history))

# if __name__ == '__main__':
#     app.run(debug=True)