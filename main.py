import os
import json
import webbrowser
import pyautogui
import psutil
import time
import speech_recognition as sr
import sounddevice as sd
import numpy as np
from urllib.parse import quote
from groq import Groq
from dotenv import load_dotenv


load_dotenv()


client = Groq(
    api_key=os.getenv("GROQ_API_KEY")
)



# ================= TOOLS =================
def listen():

    recognizer = sr.Recognizer()

    print("🎤 Listening...")


    sample_rate = 44100
    duration = 5


    recording = sd.rec(
        int(duration * sample_rate),
        samplerate=sample_rate,
        channels=1
    )

    sd.wait()


    audio_data = np.array(
        recording,
        dtype=np.float32
    )


    audio = sr.AudioData(
        audio_data.tobytes(),
        sample_rate,
        4
    )


    try:

        text = recognizer.recognize_google(audio)

        print("You:", text)

        return text


    except Exception as e:

        print("❌ Didn't understand")

        return ""

def execute(action):

    action_name = action.get("action")



    # OPEN APPS
    if action_name == "open_app":


        app = action.get("app", "").lower()


        apps = {

            "chrome": "start chrome",
            "edge": "start msedge",
            "notepad": "notepad",
            "calculator": "calc",
            "vscode": "code",
            "word": "start winword",
            "spotify": "start spotify",
            "file explorer": "explorer",
            "youtube": "start https://youtube.com"

        }



        if app in apps:

            os.system(apps[app])

            print(f"✅ Opened {app}")


        else:

            print(f"❌ App not added: {app}")




    # OPEN WEBSITE
    elif action_name == "open_website":


        url = action.get("url")


        webbrowser.open(url)


        print("✅ Website opened")




    # YOUTUBE SEARCH
    elif action_name == "youtube_search":


        query = action.get("query")


        url = (
            "https://www.youtube.com/results?search_query="
            + quote(query)
        )


        webbrowser.open(url)


        print(
            f"✅ Searching YouTube: {query}"
        )




    # CREATE FOLDER
    elif action_name == "create_folder":


        path = action.get("path")


        os.makedirs(
            path,
            exist_ok=True
        )


        print(
            f"✅ Folder created: {path}"
        )




    # CREATE FILE
    elif action_name == "create_file":


        path = action.get("path")


        with open(path, "w") as file:

            file.write("")


        print(
            f"✅ File created: {path}"
        )




    # SCREENSHOT
    elif action_name == "screenshot":


        pyautogui.screenshot(
            "screenshot.png"
        )


        print("✅ Screenshot saved")




    # SYSTEM INFO
    elif action_name == "system_info":


        print(
            "CPU:",
            psutil.cpu_percent(),
            "%"
        )


        print(
            "RAM:",
            psutil.virtual_memory().percent,
            "%"
        )




    # TYPE TEXT
    elif action_name == "type_text":


        text = action.get("text")


        time.sleep(1)


        pyautogui.write(
            text
        )


        print(
            "✅ Typed:",
            text
        )




    # PRESS KEY
    elif action_name == "press_key":


        key = action.get("key")


        pyautogui.press(
            key
        )


        print(
            "✅ Pressed:",
            key
        )




    # CLICK MOUSE
    elif action_name == "click":


        x = action.get("x")

        y = action.get("y")


        pyautogui.click(
            x,
            y
        )


        print(
            f"✅ Clicked {x},{y}"
        )




    else:


        print(
            "❌ Unknown action:",
            action_name
        )





# ================= AI BRAIN =================



SYSTEM_PROMPT = """

You are an autonomous Windows AI agent.

Understand the user's goal.

Choose actions yourself.


Available tools:


open_app

open_website

youtube_search

create_folder

create_file

screenshot

system_info

type_text

press_key

click



Return ONLY JSON array.



Example:


User:
open youtube and search stay


[
 {
  "action":"youtube_search",
  "query":"stay"
 }
]



User:
prepare my coding setup


[
 {
  "action":"open_app",
  "app":"vscode"
 },

 {
  "action":"open_app",
  "app":"chrome"
 },

 {
  "action":"create_folder",
  "path":"D:/project"
 }
]



Rules:


- Only use the tools provided.
- Never create new action names.
- Think before acting.
- Do not explain.
- Return JSON only.

"""





# ================= LOOP =================



while True:


    user = listen()



    if user.lower() == "exit":

        break



    try:



        response = client.chat.completions.create(


            model="llama-3.1-8b-instant",


            messages=[

                {

                "role":"user",

                "content":

                SYSTEM_PROMPT

                +

                "\nUser: "

                +

                user

                }

            ]

        )




        text = response.choices[0].message.content.strip()



        print(
            "AI:",
            text
        )




        text = (

            text

            .replace("```json","")

            .replace("```","")

            .strip()

        )



        actions = json.loads(text)




        if isinstance(actions, dict):

            actions = [actions]



        for action in actions:

            execute(action)



    except Exception as e:


        print(
            "❌ Error:",
            e
        )