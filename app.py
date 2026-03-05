from flask import Flask, render_template, request, session, redirect, url_for
import json
import os
from groq import Groq

app = Flask(__name__)
app.secret_key = "sovereign_alpha_key"
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_HTTPONLY'] = True

# ── PUT YOUR GROQ API KEY HERE ──
GROQ_API_KEY = os.environ.get('GROQ_API_KEY', '')


def load_database():
    db_path = os.path.join(os.path.dirname(__file__), 'database.json')
    with open(db_path, 'r') as file:
        return json.load(file)


def get_title(happiness, respect):
    avg = (happiness + respect) / 2
    if avg >= 80:   return "The Sovereign"
    elif avg >= 65: return "The Stoic"
    elif avg >= 50: return "The Realist"
    elif avg >= 35: return "The Struggler"
    else:           return "The Wounded"


@app.route('/', methods=['GET', 'POST'])
def home():
    if request.method == 'POST':
        session.clear()
        session['name'] = request.form.get('name', 'Unknown')
        session['weakness'] = request.form.get('weakness')
        session['happiness'] = 50
        session['respect'] = 50
        session['scenario_index'] = 0
        session['history'] = []
        return redirect(url_for('intro'))
    return render_template('index.html', phase='setup')


@app.route('/intro')
def intro():
    if 'name' not in session:
        return redirect(url_for('home'))
    return render_template('index.html', phase='intro',
                           name=session['name'],
                           weakness=session['weakness'],
                           happiness=session['happiness'],
                           respect=session['respect'])


@app.route('/game', methods=['GET', 'POST'])
def game():
    if 'name' not in session:
        return redirect(url_for('home'))

    db = load_database()
    weakness = session.get('weakness')
    scenarios = db.get(weakness, [])
    total = len(scenarios)

    session['happiness'] = max(0, min(100, session.get('happiness', 50)))
    session['respect'] = max(0, min(100, session.get('respect', 50)))

    if session['scenario_index'] >= total:
        return redirect(url_for('report'))

    current_scenario = scenarios[session['scenario_index']]

    if request.method == 'POST':
        choice = request.form.get('choice')
        if choice and choice in current_scenario['options']:
            selected_option = current_scenario['options'][choice]

            session['happiness'] = max(0, min(100, session['happiness'] + selected_option['h_impact']))
            session['respect']   = max(0, min(100, session['respect']   + selected_option['r_impact']))
            session['scenario_index'] += 1

            session['feedback_data'] = {
                'response':    selected_option['response'],
                'h_impact':    selected_option['h_impact'],
                'r_impact':    selected_option['r_impact'],
                'choice_text': selected_option['text'],
                'question':    current_scenario['question'],
            }

            history = session.get('history', [])
            history.append({
                'question': current_scenario['question'],
                'choice':   selected_option['text'],
                'h_impact': selected_option['h_impact'],
                'r_impact': selected_option['r_impact'],
                'response': selected_option['response'],
            })
            session['history'] = history

            net = selected_option['h_impact'] + selected_option['r_impact']
            session['streak'] = session.get('streak', 0) + 1 if net > 0 else 0
            session['max_streak'] = max(session.get('max_streak', 0), session.get('streak', 0))
            session.modified = True

        return redirect(url_for('feedback'))

    return render_template('index.html', phase='game',
                           scenario=current_scenario,
                           name=session['name'],
                           happiness=session['happiness'],
                           respect=session['respect'],
                           scenario_index=session['scenario_index'],
                           total=total,
                           streak=session.get('streak', 0))


@app.route('/feedback')
def feedback():
    if 'name' not in session or 'feedback_data' not in session:
        return redirect(url_for('game'))
    fd = session.pop('feedback_data')
    session.modified = True
    return render_template('index.html', phase='feedback',
                           name=session['name'],
                           happiness=session['happiness'],
                           respect=session['respect'],
                           response=fd['response'],
                           h_impact=fd['h_impact'],
                           r_impact=fd['r_impact'],
                           choice_text=fd['choice_text'],
                           question=fd['question'],
                           streak=session.get('streak', 0))


@app.route('/report')
def report():
    if 'name' not in session:
        return redirect(url_for('home'))
    history = session.get('history', [])
    best  = max(history, key=lambda x: x['h_impact'] + x['r_impact'], default=None)
    worst = min(history, key=lambda x: x['h_impact'] + x['r_impact'], default=None)
    positive_choices = sum(1 for h in history if h['h_impact'] + h['r_impact'] > 0)
    return render_template('index.html', phase='report',
                           name=session['name'],
                           weakness=session['weakness'],
                           happiness=session['happiness'],
                           respect=session['respect'],
                           history=history,
                           best=best,
                           worst=worst,
                           positive_choices=positive_choices,
                           total_choices=len(history),
                           max_streak=session.get('max_streak', 0))


@app.route('/coach')
def coach():
    if 'name' not in session:
        return redirect(url_for('home'))
    session['chat_history'] = []
    session['chat_count'] = 0
    session.modified = True
    return render_template('chat.html',
                           name=session['name'],
                           weakness=session['weakness'],
                           happiness=session['happiness'],
                           respect=session['respect'],
                           title=get_title(session['happiness'], session['respect']),
                           history=session.get('history', []))


@app.route('/chat', methods=['POST'])
def chat():
    if 'name' not in session:
        return {'error': 'Session expired'}, 403

    MAX_MESSAGES = 8
    chat_count = session.get('chat_count', 0)

    if chat_count >= MAX_MESSAGES:
        return {'reply': None, 'limit_reached': True, 'remaining': 0}

    data = request.get_json()
    user_message = data.get('message', '').strip()
    if not user_message:
        return {'error': 'Empty message'}, 400

    title = get_title(session['happiness'], session['respect'])

    history_text = ""
    for i, h in enumerate(session.get('history', []), 1):
        net = h['h_impact'] + h['r_impact']
        sentiment = "positive" if net > 0 else "negative" if net < 0 else "neutral"
        history_text += f"\n{i}. Situation: {h['question']}\n   They chose: {h['choice']} ({sentiment})\n   Outcome: {h['response']}\n"

    system_prompt = f"""You are a sharp, direct life coach helping {session['name']} understand themselves better.

Here is everything you know about them:
- Name: {session['name']}
- Core challenge: {session['weakness']}
- Final Happiness score: {session['happiness']}/100
- Final Respect score: {session['respect']}/100
- Personality type: {title}
- Their choices throughout the game:
{history_text}

Coaching rules:
- Be direct, warm but honest — like a mentor who genuinely cares
- Reference their SPECIFIC choices from the game when relevant
- Keep responses to 2-4 sentences max
- End with one follow-up question
- Never be preachy or lecture them"""

    chat_history = session.get('chat_history', [])
    chat_history.append({'role': 'user', 'content': user_message})

    try:
        client = Groq(api_key=GROQ_API_KEY)
        response = client.chat.completions.create(
            model='llama-3.1-8b-instant',
            max_tokens=300,
            messages=[{'role': 'system', 'content': system_prompt}] + chat_history
        )
        reply = response.choices[0].message.content
        print(f"Groq reply: {reply[:80]}...")

    except Exception as e:
        print(f"GROQ ERROR: {e}")
        return {'reply': f'Error contacting coach: {str(e)}', 'limit_reached': False, 'remaining': MAX_MESSAGES - chat_count}

    chat_history.append({'role': 'assistant', 'content': reply})
    session['chat_history'] = chat_history
    session['chat_count'] = chat_count + 1
    session.modified = True

    return {'reply': reply, 'limit_reached': False, 'remaining': MAX_MESSAGES - session['chat_count']}


if __name__ == '__main__':
    app.run(debug=True)