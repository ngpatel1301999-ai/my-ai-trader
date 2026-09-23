import subprocess
import sys
from flask import Flask, render_template, jsonify

app = Flask(__name__)

# Process track karne ke liye global variable
bot_process = None

@app.route("/")
def home():
    # Frontend HTML load hoga
    return render_template("index.html")

@app.route("/start", methods=["POST"])
def start_bot():
    global bot_process
    # Agar bot pehle se nahi chal raha hai tabhi start karega
    if bot_process is None or bot_process.poll() is not None:
        bot_process = subprocess.Popen([sys.executable, "main.py"])
        return jsonify({"message": "Bot launched and connected successfully!"}), 200
    return jsonify({"message": "Bot is already running!"}), 400

@app.route("/stop", methods=["POST"])
def stop_bot():
    global bot_process
    # Agar bot chal raha hai toh use stop karega
    if bot_process and bot_process.poll() is None:
        bot_process.terminate()
        bot_process = None
        return jsonify({"message": "Bot disconnected successfully!"}), 200
    return jsonify({"message": "Bot is not running!"}), 400

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)