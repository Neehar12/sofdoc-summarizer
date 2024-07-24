import openai
from collections import defaultdict
import time
import google.generativeai as genai
from mistralai.models.chat_completion import ChatMessage

def get_gemini_reponse(model, message):
    config = genai.GenerationConfig(max_output_tokens=4000, temperature=0)

    # Generate text
    response = model.generate_content(
        [message], generation_config=config
    )
    return response.text

def get_mistral_response(client, message):
    chat_response = client.chat(
            model="azureai",
            messages=[
                ChatMessage(
                    role="user",
                    content="You are a helpful assistant specialized in summarizing medical information.",
                ),
                ChatMessage(
                    role="user",
                    content=message,
                )
            ],
            max_tokens=1000,
            temperature=0
    )
    print('prompt_tokens:' + str(chat_response.usage.prompt_tokens))
    print('total_tokens:' + str(chat_response.usage.total_tokens))
    print('completion_tokens:' + str(chat_response.usage.completion_tokens))
    return (chat_response.choices[0].message.content, chat_response.usage.total_tokens)


def get_gpt_response(message, model="gpt-4o"):
    response = openai.ChatCompletion.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant specialized in summarizing medical information."},
                    {"role": "user", "content": message}
                ],
                max_tokens=4000
            )
    return response.choices[0].message['content']


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
        if 'patient' in resource.keys():
            resource.pop('patient')
        if 'extension' in resource.keys():
           resource.pop('extension')
        if 'identifier' in resource.keys():
           resource.pop('identifier')
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
        if 'resourceType' in resource.keys():
           resource.pop('resourceType')
        # print(resource.keys())
    # return resources

    concat_string = "\n".join([str(resource) for resource in resources])
    # print(concat_string)
    formatted_string_1 = concat_string.replace(": ", ":")
    formatted_string_2 = formatted_string_1.replace(", ", ",")
    formatted_string_3 = formatted_string_2.replace("'", "")
    # print(formatted_string_2)
    return formatted_string_3
