# from flask import Flask, request, render_template, jsonify
import requests
import openai
from openai import OpenAI
from collections import defaultdict
import app_helper
import rag_helper
import os

# app = Flask(__name__)

# Set your OpenAI API key here
openai.api_key = 'sk-proj-kHoXD3aKcluuSADuVNZBT3BlbkFJVFiHGTt0BRah1ra9ZGql'
os.environ["OPENAI_API_KEY"] = openai.api_key
metriport_api_key = 'NzNCSTZuS0ZQalVoT2pmX0tfb1laOjE3Mzg4Y2Q4LTUwOGMtNDU1ZC04YzA4LWI3MjQwMzU0YTBkYg'
API_URL = "https://api.sandbox.metriport.com/medical/v1/patient/019085d7-34f3-7392-9cff-c52f2a43a288/consolidated"
client = OpenAI(api_key=openai.api_key)

headers = {
    "x-api-key": metriport_api_key,
}

response = requests.get(API_URL, headers=headers)

print(response.status_code)
patient_history = response.json()
embedding_array = []
resource_array = []



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


print(parse_patient_history(patient_history, summarize=True))

RAG_QUERIES = ["What is the latest medication?"]

#############################################################################################
# Self Implemented RAG for Chat Q & A (HIPAA compliant) [Less accurate]

# for resource in resource_array:
#     embedding_array.append(app_helper.get_openai_embeddings(client, resource))

# while True:
#     print('Enter your query:')
#     rag_query = input()
#     query_embedding = app_helper.get_openai_embeddings(client, rag_query)
#     query_resources = rag_helper.search(query_embedding, embedding_array, resource_array)
#     # print(query_resources)
#     response = app_helper.get_gpt_response(client, "Please answer the query based on patient context provided later: " + rag_query + "Here is the patient context: " + app_helper.formatter(query_resources, remove_resource_type=False))
#     print(response)

#############################################################################################
# Langchain RAG Q & A (Need to verify HIPAA Compliant)


from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain.schema.document import Document
from langchain_openai import OpenAIEmbeddings
# from langchain_chroma import Chroma

from langchain.indexes.vectorstore import VectorstoreIndexCreator
from langchain_openai import ChatOpenAI

# text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
# docs = [Document(page_content=x) for x in text_splitter.split_text("\n".join([str(resource) for resource in resource_array]))]
# docs = [Document(page_content=app_helper.formatter([resource])) for resource in resource_array]
docs = [Document(page_content=str(resource)) for resource in resource_array]
embeddings = OpenAIEmbeddings(model="text-embedding-3-large")
# vectorstore = Chroma.from_documents(documents=docs, embedding=embeddings)
index = VectorstoreIndexCreator(embedding=embeddings).from_documents(docs)
llm = ChatOpenAI(model="gpt-4o", temperature="0")

while True:
    print('Enter your query:')
    rag_query = input()
    response = index.query(rag_query, llm=llm)
    print(response)

# if __name__ == '__main__':
#     app.run(debug=True)