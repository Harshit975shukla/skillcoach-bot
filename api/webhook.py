from flask import Flask

app = Flask(__name__)


@app.route("/", methods=["GET", "POST"])
def index():
    return "SkillCoach Bot is running.", 200
