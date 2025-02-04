from dotenv import find_dotenv, load_dotenv
import os
import json
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import CodeInterpreterTool
from azure.identity import DefaultAzureCredential
from typing import Any
from pathlib import Path
from openai import AzureOpenAI
import logging
import time
import requests
import streamlit as st
load_dotenv(find_dotenv())

client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),  
    api_version="2024-08-01-preview",
    azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    )
model = "gpt-4o"

def get_news(topic):
    url = (
        f"https://newsapi.org/v2/everything?q={topic}&apiKey={os.getenv('NEWS_API_KEY')}&pageSize=5"
    )

    try:
        # Make the HTTP request
        response = requests.get(url)
        if response.status_code == 200:
            news = json.dumps(response.json(), indent=4) # oject with payload with news
            news_json = json.loads(news) # convert the string from previous line into a python dict we can access

            data = news_json

            # access all fields, i.e loop through json and extract what we want
            status = data["status"]
            total_results = data["totalResults"]    
            articles = data["articles"] # list of articles  

            final_news = [] # empty list to populate with title descriptions

            # loop through articles & get info
            for article in articles:
                source_name = article["source"]["name"]
                author = article["author"]
                title = article["title"]
                description = article["description"]    
                url = article["url"]
                content = article["content"]
                # put everything in a string concatenated together and put into a list
                title_description = f""" 
                    Title: {title},
                    Author: {author},
                    Source: {source_name},
                    Description: {description},
                    URL: {url}
                """
                final_news.append(title_description) 
            return final_news
        else:
            return []
    except requests.exceptions.RequestException as e:
        print(f"An error occurred: {e}")
        return None


class Assistant: 
    thread_id = "thread_9RTe5MWodq4Tltdjwa6Tk7ue" # if not updated to actual thread id & assistant id it will create another assistant when rerunning with another query 
    assistant_id = "asst_naWSM3tuMb2oUg3YFBBlgECA"

    def __init__(self, model: str = model) -> None:
        self.client = client
        self.model = model
        self.assistant = None
        self.thread = None
        self.run = None
        self.summary = None

        # retrieve existing assistant and thread if IDs are already there
        if Assistant.assistant_id: 
            self.assistant = self.client.beta.assistants.retrieve(
                assistant_id = Assistant.assistant_id
            )

        if Assistant.thread_id:
            self.thread = self.client.beta.threads.retrieve(
                thread_id = Assistant.thread_id
            )

    def create_assistant(self, name, instructions, tools):
        if not self.assistant: 
            assistant_object = self.client.beta.assistants.create(
                name = name,
                instructions = instructions,
                tools = tools,
                model = self.model
            )
            Assistant.assistant_id = assistant_object.id
            self.assistant = assistant_object
            print(f"AssisID::: {self.assistant.id}")

    def create_thread(self):
        if not self.thread: # create thread object if nothing there 
            thread_object = self.client.beta.threads.create()
            Assistant.thread_id = thread_object.id
            self.thread = thread_object
            print(f"ThreadID::: {self.thread.id}")

    def add_message_to_thread(self, role, content):
        if self.thread:
            self.client.beta.threads.messages.create(
                thread_id = self.thread.id,
                role = role,
                content = content 
            )

    def run_assistant(self, instructions):
        if self.assistant and self.thread: # check if theres an assistant and a thread
            self.run = self.client.beta.threads.runs.create(
                thread_id = self.thread.id,
                assistant_id = self.assistant.id,
                instructions = instructions
            )

    def process_message(self):
        if self.thread: # check if there is a working thread to go in and get the messages
            messages = self.client.beta.threads.messages.list(thread_id = self.thread.id)
            summary = []

            last_message = messages.data[0]
            role = last_message.role
            response = last_message.content[0].text.value
            summary.append(response) 

            self.summary = "\n".join(summary)
            print(f"Summary-----> {role.capitalize()}: ==> {response}")

    def call_required_functions(self, required_actions): # call the function that is required
        if not self.run: # if run not available
            return
        tool_outputs = [] # use to go through and pull the required tools/functions

        for action in required_actions["tool_calls"]:
            func_name = action["function"]["name"] # loop throughto get names of functions
            arguments = json.loads(action["function"]["arguments"]) # get the arguments of the function

            if func_name == "get_news":
                output = get_news(topic = arguments["topic"]) 
                print(f"stuff;;{output}")
                final_str = ""
                for item in output:
                    final_str += "".join(item)

                tool_outputs.append({
                    "tool_call_id": action["id"], #tool id comes from action, go thru all tool calls and get the id
                    "output": final_str
                })
            else:
                raise ValueError(f"Unknown function: {func_name}")

        print("Submitting outputs back to the Assistant...")
        self.client.beta.threads.runs.submit_tool_outputs(
            thread_id = self.thread.id,
            run_id = self.run.id,
            tool_outputs = tool_outputs
        )

    # for streamlit
    def get_summary(self):
        return self.summary
    

    def wait_for_completion(self):
        if self.thread and self.run:
            while True:
                time.sleep(5)
                run_status = self.client.beta.threads.runs.retrieve(
                    thread_id = self.thread.id,
                    run_id = self.run.id
                )
                print(f"Run Status:: {run_status.model_dump_json(indent=4)}")

                if run_status.status == "completed":
                    self.process_message()  # call the process message function, means the running is completed and we should have an answer
                    break
                elif run_status.status == "requires_action": # when status is required actions, call required functions, get all the tools
                    print("FUNCTION CALLING NOW...")
                    self.call_required_functions(
                        required_actions = run_status.required_action.submit_tool_outputs.model_dump() # get submitted tools, make a model dump so its a python dict
                    )

    
    # run the steps
    def run_steps(self):
        run_steps = self.client.beta.threads.runs.steps.list(
            thread_id = self.thread.id,
            run_id = self.run.id
        )
        print(f"Run-Steps::: {run_steps}")
        return run_steps.data


def main():
    # news = get_news("bitcoin")
    # print(news[0])

    manager = Assistant()

    # streamlit interface
    st.title("News Summarizer")

    with st.form(key="user_input_form"):
        instructions = st.text_input("Enter Topic:")
        submit_button = st.form_submit_button(label="Run Assistant")

        if submit_button:
            manager.create_assistant(
                name = "News Summarizer",
                instructions = "You are a personal article summarizer assistant who knows how to take a list of article's titles and descriptions and then write a short summary of all the news articles ",
                tools = [
                    {
                    "type": "function", 
                     "function": {
                         "name": "get_news",
                         "description": "get the latest news articles on a given topic",
                         "parameters": {
                             "type": "object",
                             "properties": {
                                 "topic": {
                                     "type": "string",
                                     "description": "The topic to get news about"
                                 }
                             },
                             "required": ["topic"]
                         },
                    },
                },]
                
            )

            manager.create_thread()

            # add message and run the assistant
            manager.add_message_to_thread(
                role = "user",
                content = f"Summarize the news on this topic {instructions}"
            )
            manager.run_assistant(instructions="Summarize the news")

            # wait for completions and process messages
            manager.wait_for_completion()

            summary = manager.get_summary()

            st.write(summary)

            st.text("Run Steps:") # text to show run steps at the bottom
            st.code(manager.run_steps(), line_numbers=True)


if __name__ == "__main__":
    main()