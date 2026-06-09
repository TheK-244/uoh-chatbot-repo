from flask import jsonify, request, session

from ai_service import (
    build_ai_reply,
    conversational_reply,
    greeting_reply,
    is_conversational_message,
    is_greeting,
    build_found_results_response,
    get_ambiguous_database_options,
    reliable_internal_results,
    get_previous_ambiguity_question,
    needs_basic_clarification,
    split_greeting_and_question,
)
from retrieval_service import get_query_embedding, search_similar_documents
from web_search_service import restricted_web_search
from config import ENABLE_WEB_SEARCH, MIN_SIMILARITY_SCORE, TOP_K
from conversation_service import get_or_create_conversation, get_recent_messages, save_message, touch_conversation
from database import execute_fetchall, execute_fetchone, get_connection
from decorators import login_required


# يسجل مسارات الشات والمحادثات.
def register_chat_routes(app):
    # يرجع قائمة محادثات المستخدم الحالي بصيغة JSON.
    @app.route("/conversations")
    @login_required
    def list_conversations():
        conversations = execute_fetchall(
            """
            SELECT id, title, created_at
            FROM conversations
            WHERE user_id = %s
            ORDER BY updated_at DESC, id DESC
            """,
            (session["user_id"],),
        )
        return jsonify({"conversations": conversations})

    # يستقبل رسالة المستخدم ويولد الرد ويحفظ المحادثة.
    @app.route("/chat", methods=["POST"])
    @login_required
    def chat():
        data = request.get_json(silent=True) or {}
        user_message = (data.get("message") or "").strip()
        conversation_id = data.get("conversation_id")

        if not user_message:
            return jsonify({"reply": "Message is required."}), 400

        try:
            conversation_id = get_or_create_conversation(session["user_id"], conversation_id, user_message)
            recent_messages = get_recent_messages(conversation_id)
            save_message(conversation_id, "user", user_message)

            previous_ambiguity_question = get_previous_ambiguity_question(recent_messages)

            if previous_ambiguity_question:
                # The bot already asked for more details once. Try to narrow the
                # previous ambiguous question using the user's follow-up. If it
                # still remains ambiguous, show the results found instead of
                # asking for details again or forcing numeric selection.
                search_query = f"{previous_ambiguity_question} {user_message}".strip()
                query_embedding = get_query_embedding(search_query)
                results = search_similar_documents(query_embedding, query_text=search_query, top_k=TOP_K)
                web_results = []

                ambiguous_options = get_ambiguous_database_options(results)
                if ambiguous_options:
                    reply = build_found_results_response(results, user_message)
                else:
                    internal_result_is_weak = not reliable_internal_results(results)
                    if internal_result_is_weak and ENABLE_WEB_SEARCH:
                        web_results = restricted_web_search(search_query)
                    recent_messages = get_recent_messages(conversation_id)
                    reply = build_ai_reply(user_message, results, recent_messages, web_results, search_query=search_query)
            elif is_greeting(user_message):
                reply = greeting_reply(user_message)
            elif is_conversational_message(user_message):
                # Casual messages should be answered directly. They should not
                # hit database/web retrieval, otherwise stored greeting examples
                # can make the bot look rigid and unintelligent.
                reply = conversational_reply(user_message)
            else:
                # Remove greeting words before retrieval. A message like
                # "السلام عليكم وين القبول؟" should search for "وين القبول؟",
                # not for the greeting.
                _, search_query = split_greeting_and_question(user_message)
                search_query = search_query or user_message

                query_embedding = get_query_embedding(search_query)
                results = search_similar_documents(query_embedding, query_text=search_query, top_k=TOP_K)

                web_results = []
                internal_result_is_weak = not reliable_internal_results(results)

                # إذا كانت قاعدة البيانات لا تحتوي نتيجة موثوقة، نجرب البحث المحدود قبل طلب التوضيح.
                # الاعتماد على رقم التشابه وحده سبب خلطًا بين قاعدة البيانات والبحث الخارجي.
                if internal_result_is_weak and ENABLE_WEB_SEARCH:
                    web_results = restricted_web_search(search_query)

                should_clarify, clarification = needs_basic_clarification(
                    search_query,
                    results,
                    recent_messages,
                    web_results,
                )

                if should_clarify:
                    reply = clarification
                else:
                    recent_messages = get_recent_messages(conversation_id)
                    reply = build_ai_reply(user_message, results, recent_messages, web_results, search_query=search_query)

            save_message(conversation_id, "assistant", reply)
            touch_conversation(conversation_id)

            return jsonify({"reply": reply, "conversation_id": conversation_id})
        except Exception as e:
            return jsonify({"reply": f"Server error: {str(e)}"}), 500

    # يجلب رسائل محادثة محددة بعد التأكد أنها تخص المستخدم.
    @app.route("/conversation/<int:conversation_id>")
    @login_required
    def load_conversation(conversation_id):
        row = execute_fetchone(
            "SELECT id FROM conversations WHERE id = %s AND user_id = %s",
            (conversation_id, session["user_id"]),
        )
        if not row:
            return jsonify({"error": "Not found"}), 404
        messages = execute_fetchall(
            "SELECT role, content FROM messages WHERE conversation_id = %s ORDER BY id",
            (conversation_id,),
        )
        return jsonify({"conversation_id": conversation_id, "messages": messages})

    # يحذف محادثة تخص المستخدم الحالي فقط.
    @app.route("/conversation/<int:conversation_id>/delete", methods=["POST"])
    @login_required
    def delete_own_conversation(conversation_id):
        row = execute_fetchone(
            "SELECT id FROM conversations WHERE id = %s AND user_id = %s",
            (conversation_id, session["user_id"]),
        )
        if not row:
            return jsonify({"error": "Not found"}), 404

        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM conversations WHERE id = %s AND user_id = %s",
            (conversation_id, session["user_id"]),
        )
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"ok": True, "deleted_id": conversation_id})

    # ينشئ محادثة جديدة فارغة للمستخدم.
    @app.route("/conversation/new", methods=["POST"])
    @login_required
    def new_conversation():
        conversation_id = get_or_create_conversation(session["user_id"], None, "New conversation")
        return jsonify({"conversation_id": conversation_id})
