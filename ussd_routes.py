# ============================================================
# AGRITRUE PROFESSIONAL USSD + VOICE AGRICULTURAL SEARCH
# Replace your existing /ussd route with this complete section.
# This code uses generate_farming_chat_reply() from agri_analyzer.py.
# ============================================================

USSD_MAIN_MENU = """
<strong>Welcome to AgriTrue USSD Services</strong><br><br>
1. Crop health guidance<br>
2. Livestock health guidance<br>
3. Soil and fertiliser guidance<br>
4. Pest management<br>
5. Market preparation<br>
6. Weather preparedness<br>
7. Ask an agricultural question<br>
8. Open Smart Analyzer<br>
9. Check an agricultural claim<br>
0. Exit
"""

USSD_MENU_RESPONSES = {
    "1": (
        "🌱 <strong>Crop health guidance</strong><br>"
        "Inspect both sides of affected leaves, stems and fruits. "
        "Take a clear photo and use the Smart Analyzer for visible disease, "
        "pest or nutrient-deficiency screening."
    ),
    "2": (
        "🐄 <strong>Livestock health guidance</strong><br>"
        "Separate an animal showing severe weakness, breathing difficulty, "
        "heavy bleeding or inability to stand, and contact a qualified "
        "veterinary professional immediately."
    ),
    "3": (
        "🧪 <strong>Soil and fertiliser guidance</strong><br>"
        "Use a current soil test before applying fertiliser. Match the crop, "
        "growth stage, soil pH and nutrient results to the recommended input."
    ),
    "4": (
        "🐛 <strong>Pest management</strong><br>"
        "Confirm the pest before spraying. Use field scouting, sanitation, "
        "crop rotation and approved integrated pest-management measures."
    ),
    "5": (
        "📈 <strong>Market preparation</strong><br>"
        "Compare several buyers, confirm grade requirements, calculate "
        "transport and handling costs, and avoid relying on one quoted price."
    ),
    "6": (
        "🌦️ <strong>Weather preparedness</strong><br>"
        "Use a trusted local forecast before planting, spraying, irrigating "
        "or harvesting. Protect inputs and harvested produce from moisture."
    ),
    "7": (
        "💬 <strong>Ask AgriTrue</strong><br>"
        "Use the agricultural search box below or tap the microphone and ask "
        "your question in English or Kiswahili."
    ),
    "8": (
        "📷 <strong>Smart Analyzer</strong><br>"
        "Open the analyzer to photograph a crop or animal, or scan a farm "
        "document for AI-assisted screening."
    ),
    "9": (
        "🛡️ <strong>Claim checking</strong><br>"
        "Paste or speak the agricultural claim in the search box. AgriTrue "
        "will explain what can be supported and what needs verification."
    ),
    "0": "👋 Thank you for using AgriTrue. Stay informed and farm safely.",
}


def _save_ussd_log(code_entered, response_given):
    """Save a USSD/search interaction without breaking the user request."""
    try:
        db.session.add(
            USSDLog(
                code_entered=str(code_entered or "")[:500],
                response_given=str(response_given or "")[:10000],
            )
        )
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Could not save USSD interaction")


@app.route("/ussd", methods=["GET", "POST"])
def ussd():
    """
    Render the professional simulator and support traditional form submissions.
    Voice recognition and speech playback are handled in the browser.
    """
    if request.method == "GET":
        return render_template(
            "ussd.html",
            response=None,
            session_level="",
        )

    ussd_code = request.form.get("ussd_code", "").strip()
    session_level = request.form.get("session_level", "").strip()

    if not ussd_code:
        response = "Enter *456# to begin."
        next_level = ""
    elif ussd_code == "*456#" and session_level == "":
        response = USSD_MAIN_MENU
        next_level = "main_menu"
    elif session_level == "main_menu":
        response = USSD_MENU_RESPONSES.get(
            ussd_code,
            "❌ Invalid selection. Enter a number from 0 to 9.",
        )
        next_level = "" if ussd_code == "0" else "main_menu"
    else:
        response = "Enter *456# to begin."
        next_level = ""

    _save_ussd_log(ussd_code, response)

    return render_template(
        "ussd.html",
        response=response,
        session_level=next_level,
    )


@app.route("/api/ussd/search", methods=["POST"])
def ussd_search():
    """
    Answer typed or voice-transcribed agricultural questions.

    The API key remains on the server because the browser calls this route,
    not Gemini directly.
    """
    payload = request.get_json(silent=True) or {}
    question = " ".join(str(payload.get("question", "")).split())
    language = str(payload.get("language", "en-KE")).strip()

    if not question:
        return jsonify({
            "success": False,
            "error": "Please enter or speak an agricultural question.",
        }), 400

    if len(question) < 3:
        return jsonify({
            "success": False,
            "error": "Please provide a more complete question.",
        }), 400

    if len(question) > 700:
        return jsonify({
            "success": False,
            "error": "Your question is too long. Keep it below 700 characters.",
        }), 400

    is_swahili = language.lower().startswith("sw")
    response_language = "Kiswahili" if is_swahili else "clear Kenyan English"

    prompt = f"""
You are AgriTrue, a careful agricultural information assistant serving farmers
in Kenya and East Africa.

Answer the following question in {response_language}.

Requirements:
- Give a direct, practical answer.
- Use short paragraphs or brief numbered steps.
- Do not invent live weather, market prices, laboratory results or legal facts.
- Clearly state when local inspection, testing, a veterinarian, an agronomist,
  an extension officer or an issuing institution is needed.
- For crop chemicals, veterinary medicines, fertilisers and pesticides, do not
  prescribe an unsafe dose. Tell the user to follow the approved product label
  and local professional guidance.
- Treat image-only diagnosis as screening, not certainty.
- Keep the answer below 280 words.

Farmer's question:
{question}
""".strip()

    try:
        answer = generate_farming_chat_reply(prompt)
        answer = str(answer or "").strip()

        if not answer:
            raise AnalyzerError("The agricultural assistant returned an empty response.")

        _save_ussd_log(question, answer)

        return jsonify({
            "success": True,
            "question": question,
            "answer": answer,
            "language": "sw-KE" if is_swahili else "en-KE",
        })

    except AnalyzerError as exc:
        current_app.logger.warning("USSD agricultural search failed: %s", exc)
        return jsonify({
            "success": False,
            "error": str(exc),
        }), 503
    except Exception:
        current_app.logger.exception("Unexpected USSD agricultural search error")
        return jsonify({
            "success": False,
            "error": "AgriTrue could not answer right now. Please try again.",
        }), 500