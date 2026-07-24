# ============================================================
# AGRITRUE USSD COMPLETE FIX
# Remove your current /ussd route and replace it with this whole section.
# Place this section AFTER the USSDLog model and BEFORE:
#     if __name__ == "__main__":
# ============================================================

USSD_MAIN_MENU = """
<strong>Welcome to AgriTrue USSD Services</strong><br><br>
1. Crop Health Guidance<br>
2. Livestock Health Guidance<br>
3. Soil & Fertiliser Guidance<br>
4. Pest Management<br>
5. Market Preparation<br>
6. Weather Preparedness<br>
7. Ask AgriTrue<br>
8. Open Smart Analyzer<br>
9. Check an Agricultural Claim<br>
0. Exit
"""

USSD_MENU_RESPONSES = {
    "1": (
        "🌱 <strong>Crop Health Guidance</strong><br>"
        "Inspect affected leaves, stems, roots and fruits carefully. "
        "Take clear photos in natural light and use the Smart Analyzer "
        "for AI-assisted disease, pest or nutrient-deficiency screening."
    ),
    "2": (
        "🐄 <strong>Livestock Health Guidance</strong><br>"
        "Separate animals showing severe weakness, breathing difficulty, "
        "heavy bleeding, seizures or inability to stand. "
        "Contact a qualified veterinary professional immediately."
    ),
    "3": (
        "🧪 <strong>Soil & Fertiliser Guidance</strong><br>"
        "Use a current soil test before applying fertiliser. Match the crop, "
        "growth stage, soil pH and nutrient results to an approved recommendation."
    ),
    "4": (
        "🐛 <strong>Pest Management</strong><br>"
        "Confirm the pest before spraying. Use field scouting, sanitation, "
        "crop rotation and approved integrated pest-management measures."
    ),
    "5": (
        "📈 <strong>Market Preparation</strong><br>"
        "Compare several buyers, confirm grading requirements, calculate "
        "transport and handling costs, and avoid relying on one quoted price."
    ),
    "6": (
        "🌦️ <strong>Weather Preparedness</strong><br>"
        "Use a trusted local forecast before planting, spraying, irrigating "
        "or harvesting. Protect seed, fertiliser and produce from moisture."
    ),
    "7": (
        "💬 <strong>Ask AgriTrue</strong><br>"
        "Use the agricultural search box on this page or tap the microphone. "
        "Your question will be displayed, answered and read aloud."
    ),
    "8": (
        "📷 <strong>Smart Analyzer</strong><br>"
        "Open the Smart Analyzer to photograph a crop or animal, or scan a "
        "farm document for AI-assisted screening."
    ),
    "9": (
        "🛡️ <strong>Agricultural Claim Check</strong><br>"
        "Type or speak the claim in the AgriTrue search box. "
        "AgriTrue will explain what is supported and what needs verification."
    ),
    "0": (
        "👋 <strong>Thank you for using AgriTrue.</strong><br>"
        "Stay informed, verify critical decisions locally and farm safely."
    ),
}


def save_ussd_log(code_entered, response_given):
    """Save a USSD interaction without breaking the user request."""
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
    response = None
    session_level = ""

    if request.method == "POST":
        ussd_code = request.form.get("ussd_code", "").strip()
        session_level = request.form.get("session_level", "").strip()

        if not ussd_code:
            response = "Enter <strong>*456#</strong> to begin."
            session_level = ""

        elif ussd_code == "*456#" and not session_level:
            response = USSD_MAIN_MENU
            session_level = "main_menu"

        elif session_level == "main_menu":
            response = USSD_MENU_RESPONSES.get(
                ussd_code,
                "❌ Invalid selection. Enter a number from 0 to 9.",
            )

            if ussd_code == "0":
                session_level = ""
            else:
                session_level = "main_menu"

        else:
            response = "Enter <strong>*456#</strong> to begin."
            session_level = ""

        save_ussd_log(ussd_code, response)

    return render_template(
        "ussd.html",
        response=response,
        session_level=session_level,
    )


@app.route("/api/ussd/search", methods=["POST"])
def ussd_search():
    payload = request.get_json(silent=True) or {}

    question = " ".join(
        str(payload.get("question", "")).split()
    )
    language = str(
        payload.get("language", "en-KE")
    ).strip()

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
            "error": "Keep your question below 700 characters.",
        }), 400

    is_swahili = language.lower().startswith("sw")
    response_language = (
        "Kiswahili"
        if is_swahili
        else "clear Kenyan English"
    )

    prompt = f"""
You are AgriTrue, an agricultural information assistant serving
farmers in Kenya and East Africa.

Answer the farmer's question in {response_language}.

Requirements:
- Give a direct and practical answer.
- Use short paragraphs or brief numbered steps.
- Do not invent live weather, market prices, laboratory findings or official records.
- State when local inspection, testing, a veterinarian, agronomist or extension officer is needed.
- Do not prescribe unsafe pesticide, fertiliser or veterinary medicine doses.
- Keep the response below 280 words.

Farmer's question:
{question}
""".strip()

    try:
        answer = generate_farming_chat_reply(prompt)
        answer = str(answer or "").strip()

        if not answer:
            raise AnalyzerError(
                "The agricultural assistant returned an empty response."
            )

        save_ussd_log(question, answer)

        return jsonify({
            "success": True,
            "question": question,
            "answer": answer,
            "language": "sw-KE" if is_swahili else "en-KE",
        })

    except AnalyzerError as exc:
        current_app.logger.warning(
            "USSD agricultural search failed: %s",
            exc,
        )
        return jsonify({
            "success": False,
            "error": str(exc),
        }), 503

    except Exception:
        current_app.logger.exception(
            "Unexpected USSD agricultural search error"
        )
        return jsonify({
            "success": False,
            "error": (
                "AgriTrue could not answer right now. "
                "Please try again."
            ),
        }), 500