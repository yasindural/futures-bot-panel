import requests

url = "http://localhost:5000/webhook"
data = {
    "ticker": "RUNEUSDT",
    "dir": "LONG",
    "entry": 0.863
}

response = requests.post(url, json=data)
print("Status Code:", response.status_code)
print("Response:", response.text)

