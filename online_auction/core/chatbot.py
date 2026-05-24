import nltk
from nltk.tokenize import word_tokenize
from nltk.stem import WordNetLemmatizer
from nltk.metrics import edit_distance
from nltk.tag import pos_tag
import json
import torch
from transformers import BertTokenizer, BertForSequenceClassification, T5Tokenizer, T5ForConditionalGeneration
import random
import os
import logging
import datetime
import re

try:
    import spacy
    nlp = spacy.load("en_core_web_sm")
except (OSError, ImportError):
    logging.getLogger(__name__).warning(
        "spaCy not found or model 'en_core_web_sm' not downloaded. Entity recognition will be disabled.")
    nlp = None

# Download NLTK resources
nltk_data_path = os.path.join(os.path.dirname(__file__), 'nltk_data')
if not os.path.exists(nltk_data_path):
    os.makedirs(nltk_data_path)
nltk.download('punkt', download_dir=nltk_data_path)
nltk.download('wordnet', download_dir=nltk_data_path)
nltk.download('stopwords', download_dir=nltk_data_path)
nltk.download('averaged_perceptron_tagger_eng', download_dir=nltk_data_path)

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Configure NLTK path
nltk.data.path.append(nltk_data_path)

class Chatbot:
    def __init__(self):
        self.lemmatizer = WordNetLemmatizer()
        self.intents_file = os.path.join(os.path.dirname(__file__), 'intents.json')
        self.new_questions_file = os.path.join(os.path.dirname(__file__), 'new_questions.json')
        self.history_file = os.path.join(os.path.dirname(__file__), 'conversation_history.json')
        self.answered_questions_file = os.path.join(os.path.dirname(__file__), 'answered_questions.json')
        self.model_dir = os.path.join(os.path.dirname(__file__), 'chatbot_bert_model')
        self.t5_model_dir = os.path.join(os.path.dirname(__file__), 'chatbot_t5_model')

        # Ensure files exist
        for file_path in [self.intents_file, self.new_questions_file, self.history_file, self.answered_questions_file]:
            if not os.path.exists(file_path):
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump({}, f)
                logger.warning(f"Created empty {file_path}")

        self.intents = self.load_intents()
        self.tokenizer = self.load_tokenizer()

        # Initialize new questions, history, and answered questions
        self.new_questions = self.load_new_questions()
        self.answered_questions = self.load_answered_questions()
        self.history = self.load_conversation_history()

        # Load BERT model and label map
        self.model = None
        self.label_map = {}
        try:
            self.model = BertForSequenceClassification.from_pretrained(self.model_dir)
            self.model.eval()
            label_map_path = os.path.join(self.model_dir, 'label_map.json')
            with open(label_map_path, 'r', encoding='utf-8') as f:
                self.label_map = json.load(f)
                self.label_map = {int(k): v for k, v in self.label_map.items()}
            logger.debug(f"Loaded label map: {self.label_map}")
            print("Loaded BERT model from:", self.model_dir)
        except Exception as e:
            logger.error(f"Failed to load BERT model or label map: {e}")
            self.model = None

        # Load T5 model
        self.t5_tokenizer = None
        self.t5_model = None
        try:
            self.t5_tokenizer = T5Tokenizer.from_pretrained(self.t5_model_dir)
            self.t5_model = T5ForConditionalGeneration.from_pretrained(self.t5_model_dir)
            self.t5_model.eval()
            logger.debug("Loaded T5 model")
            print("Loaded T5 model from:", self.t5_model_dir)
        except Exception as e:
            logger.warning(f"Failed to load T5 model: {e}. Using static responses only.")
            try:
                self.t5_tokenizer = T5Tokenizer.from_pretrained("t5-small")
                self.t5_model = T5ForConditionalGeneration.from_pretrained("t5-small")
                self.t5_model.eval()
                logger.debug("Loaded fallback T5-small model")
            except Exception as e2:
                logger.error(f"Failed to load fallback T5 model: {e2}")

        # Load entity map
        self.entity_map = {
            "category": ["luxury watches", "rare collectibles", "luxury cars", "jewelry & diamonds"],
        }

        self.intent_tags = [intent['tag'] for intent in self.intents['intents']]
        self.dialogue_state = None
        self.tag_to_responses = self._build_response_map()

        # Build keyword index and pattern set
        self.intent_keywords = {}
        self.intent_patterns = {}
        for intent in self.intents['intents']:
            words = set()
            patterns = set()
            for pattern in intent['patterns']:
                words.update(word_tokenize(pattern.lower()))
                patterns.add(pattern.lower())
            self.intent_keywords[intent['tag']] = words
            self.intent_patterns[intent['tag']] = patterns
            print(f"Intent {intent['tag']} loaded with {len(intent['patterns'])} patterns")

    def load_intents(self):
        try:
            with open(self.intents_file, 'r', encoding='utf-8') as f:
                intents = json.load(f)
                if not isinstance(intents, dict) or 'intents' not in intents:
                    raise ValueError("Invalid intents.json format")
                for intent in intents['intents']:
                    if not intent.get('tag') or not intent.get('patterns') or not intent.get('responses'):
                        logger.warning(f"Invalid intent {intent.get('tag', 'unknown')}: missing tag, patterns, or responses")
                    elif not isinstance(intent['responses'], list) or not all(isinstance(r, str) or (isinstance(r, dict) and 'tag' in r and 'responses' in r) for r in intent['responses']):
                        logger.warning(f"Invalid responses for intent {intent['tag']}")
                print("Loaded intents with tags:", [intent['tag'] for intent in intents['intents']])
                return intents
        except FileNotFoundError:
            logger.error(f"{self.intents_file} not found.")
            return {"intents": []}
        except json.JSONDecodeError as e:
            logger.error(f"Error decoding {self.intents_file}: {e}")
            return {"intents": []}

    def load_tokenizer(self):
        try:
            return BertTokenizer.from_pretrained(self.model_dir)
        except Exception as e:
            logger.error(f"Failed to load tokenizer: {e}")
            return None

    def load_answered_questions(self):
        try:
            with open(self.answered_questions_file, 'r', encoding='utf-8') as f:
                answered_questions = json.load(f)
                if not isinstance(answered_questions, dict) or 'questions' not in answered_questions:
                    return {"questions": []}
                print("Loaded answered questions:", [q['text'] for q in answered_questions['questions']])
                return answered_questions
        except (FileNotFoundError, json.JSONDecodeError):
            return {"questions": []}

    def save_answered_questions(self):
        try:
            with open(self.answered_questions_file, 'w', encoding='utf-8') as f:
                json.dump(self.answered_questions, f, indent=2)
                print("Saved answered_questions.json with", len(self.answered_questions['questions']), "questions")
        except Exception as e:
            logger.error(f"Error saving answered questions: {e}")

    def _build_response_map(self):
        response_map = {}
        for intent in self.intents['intents']:
            if 'responses' not in intent or not intent['responses']:
                logger.warning(f"Intent '{intent['tag']}' has no valid responses. Skipping.")
                continue
            if isinstance(intent['responses'], list) and all(isinstance(sub, dict) and 'tag' in sub and 'responses' in sub for sub in intent['responses']):
                sub_responses = {}
                for sub in intent['responses']:
                    if isinstance(sub['responses'], list) and sub['responses']:
                        sub_responses[sub['tag']] = sub['responses']
                    else:
                        logger.warning(f"Sub-response '{sub['tag']}' in intent '{intent['tag']}' has no valid responses.")
                if sub_responses:
                    response_map[intent['tag']] = sub_responses
                else:
                    logger.warning(f"No valid sub-responses for intent '{intent['tag']}'. Skipping.")
            else:
                responses = intent['responses'] if isinstance(intent['responses'], list) else [intent['responses']]
                if responses and all(isinstance(r, str) and r.strip() for r in responses):
                    response_map[intent['tag']] = responses
                else:
                    logger.warning(f"Invalid responses for intent '{intent['tag']}': {responses}. Skipping.")
        return response_map

    def load_new_questions(self):
        try:
            with open(self.new_questions_file, 'r', encoding='utf-8') as f:
                new_questions = json.load(f)
                print("Loaded new questions:", [q['text'] for q in new_questions['questions']])
                return new_questions
        except (FileNotFoundError, json.JSONDecodeError):
            return {"questions": []}

    def save_new_questions(self):
        try:
            with open(self.new_questions_file, 'w', encoding='utf-8') as f:
                json.dump(self.new_questions, f, indent=2)
                print("Saved new_questions.json with", len(self.new_questions['questions']), "questions")
        except Exception as e:
            logger.error(f"Error saving new questions: {e}")

    def load_conversation_history(self, user_id="default"):
        try:
            with open(self.history_file, 'r', encoding='utf-8') as f:
                history_data = json.load(f)
                return history_data.get(user_id, [])[:3]
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def save_conversation(self, user_id, user_input, response, intent, entities, escalated=False):
        try:
            history_data = {}
            if os.path.exists(self.history_file):
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    history_data = json.load(f)
            if user_id not in history_data:
                history_data[user_id] = []
            history_data[user_id].insert(0, {
                "input": user_input,
                "response": response,
                "intent": intent,
                "entities": entities,
                "escalated": escalated,
                "timestamp": str(datetime.datetime.now())
            })
            history_data[user_id] = history_data[user_id][:3]
            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump(history_data, f, indent=2)
            logger.debug(f"Saved conversation for user {user_id}, escalated: {escalated}")
        except Exception as e:
            logger.error(f"Error saving conversation: {e}")

    def preprocess(self, text):
        try:
            if isinstance(text, bytes):
                text = text.decode('utf-8', errors='replace')
            text = text.replace('sealedand', 'sealed bid').replace(',', ' ').replace('  ', ' ')
            tokens = word_tokenize(text.lower())
            pos_tags = pos_tag(tokens)
            lemmatized = [self.lemmatizer.lemmatize(token) for token, _ in pos_tags if
                          token.isalnum() or token in [',', '.']]
            processed = ' '.join(lemmatized)
            logger.debug(f"Preprocessed '{text}' to '{processed}' with POS: {pos_tags}")
            return processed if processed else text.lower()
        except Exception as e:
            logger.error(f"Preprocessing error: {e}")
            return text.lower()

    def extract_entities(self, text):
        entities = {}
        if nlp:
            try:
                doc = nlp(text)
                for ent in doc:
                    ent_text = ent.text.lower()
                    for entity_type, values in self.entity_map.items():
                        if ent_text in values:
                            entities[entity_type] = ent_text
                            break
            except Exception as e:
                logger.error(f"spaCy entity extraction failed: {e}")
        logger.debug(f"Entities extracted: {entities}")
        return entities

    def is_affirmation(self, message):
        try:
            if isinstance(message, bytes):
                message = message.decode('utf-8', errors='replace')
            message_lower = message.lower()
            affirmatives = [
                'yes', 'yeah', 'yep', 'sure', 'ok', 'okay', 'cool', 'alright', 'yup',
                'fine', 'i do', 'got it', 'sounds good', 'definitely', 'for sure'
            ]
            return any(word in message_lower for word in affirmatives)
        except Exception as e:
            logger.error(f"Affirmation detection error: {e}")
            return False

    def fuzzy_match(self, message, threshold=0.65):
        try:
            if isinstance(message, bytes):
                message = message.decode('utf-8', errors='replace')
            message_lower = message.lower()
            tokens = set(word_tokenize(message_lower))
            entities = self.extract_entities(message)
            min_distance = float('inf')
            best_match = None
            best_score = 0
            is_question = any(word in message_lower for word in ['what', 'how', 'why', 'when', 'where'])
            is_affirm = self.is_affirmation(message)
            is_new_user = any(
                phrase in message_lower for phrase in ['new', 'dont know', "don't know", 'guide', 'beginner'])

            if message_lower.startswith('hll') or message_lower in ['hlo', 'hllo']:
                message_lower = 'hello'

            for tag, patterns in self.intent_patterns.items():
                for pattern in patterns:
                    pattern_tokens = set(word_tokenize(pattern.lower()))
                    overlap = len(tokens.intersection(pattern_tokens)) / max(len(tokens), len(pattern_tokens), 1)
                    distance = edit_distance(message_lower, pattern)
                    similarity = 1 - (distance / max(len(message_lower), len(pattern)))
                    combined_score = 0.6 * overlap + 0.4 * similarity
                    weight = 1.0
                    if is_question and tag in ['auctions_overview', 'bidding_overview', 'platform_overview', 'registration_info', 'auction_type']:
                        weight = 1.4
                    elif is_affirm and tag == 'affirmation':
                        weight = 2.0
                    elif is_new_user and tag in ['help', 'registration_info', 'platform_overview']:
                        weight = 1.8
                    elif self.dialogue_state and tag == self.dialogue_state:
                        weight = 1.2
                    elif entities.get('category') and tag == 'categories':
                        weight *= 1.4
                    if len(tokens) <= 2 and any(word in pattern_tokens for word in tokens):
                        weight *= 1.5
                    weighted_score = combined_score * weight
                    if weighted_score > threshold and weighted_score > best_score:
                        best_score = weighted_score
                        best_match = tag
                        min_distance = distance
            logger.debug(f"Fuzzy match result: {best_match}, score: {best_score:.2f}")
            return best_match, best_score
        except Exception as e:
            logger.error(f"Fuzzy match error: {e}")
            return None, 0

    def fuzzy_match_answered_questions(self, message, threshold=0.65):
        try:
            message_lower = message.lower()
            tokens = set(word_tokenize(message_lower))
            best_match = None
            best_score = 0
            best_answer = None
            best_intent = None

            for question in self.answered_questions['questions']:
                q_text = question['text'].lower()
                q_tokens = set(word_tokenize(q_text))
                overlap = len(tokens.intersection(q_tokens)) / max(len(tokens), len(q_tokens), 1)
                distance = edit_distance(message_lower, q_text)
                similarity = 1 - (distance / max(len(message_lower), len(q_text)))
                combined_score = 0.6 * overlap + 0.4 * similarity
                if combined_score > threshold and combined_score > best_score:
                    best_score = combined_score
                    best_match = q_text
                    best_answer = question['answer']
                    best_intent = question['intent']
            logger.debug(f"Fuzzy match answered questions: match='{best_match}', score={best_score:.2f}, intent={best_intent}")
            return best_match, best_answer, best_intent, best_score
        except Exception as e:
            logger.error(f"Fuzzy match answered questions error: {e}")
            return None, None, None, 0

    def pattern_match(self, message, intent_tag):
        try:
            message_lower = message.lower()
            message_tokens = set(word_tokenize(message_lower))
            for intent in self.intents['intents']:
                if intent['tag'] == intent_tag:
                    for pattern in intent['patterns']:
                        pattern_tokens = set(word_tokenize(pattern.lower()))
                        overlap = len(message_tokens.intersection(pattern_tokens)) / max(len(message_tokens), len(pattern_tokens), 1)
                        distance = edit_distance(message_lower, pattern.lower())
                        similarity = 1 - (distance / max(len(message_lower), len(pattern)))
                        if overlap > 0.5 or similarity > 0.65:
                            logger.debug(f"Pattern match for '{message}' with '{pattern}' in intent '{intent_tag}', overlap: {overlap:.2f}, similarity: {similarity:.2f}")
                            return True
                    break
            logger.debug(f"No pattern match for '{message}' in intent '{intent_tag}'")
            return False
        except Exception as e:
            logger.error(f"Pattern match error: {e}")
            return False

    def store_new_question(self, message):
        try:
            if message.strip() and message.lower() not in [q['text'].lower() for q in self.new_questions['questions']]:
                self.new_questions['questions'].append({
                    "text": message,
                    "intent": "unknown",
                    "timestamp": str(datetime.datetime.now()),
                    "answered": False,
                    "answer": None
                })
                self.save_new_questions()
                logger.debug(f"Stored new question: {message}")
            else:
                logger.debug(f"Question '{message}' already exists or is empty, not storing.")
        except Exception as e:
            logger.error(f"Error storing new question: {e}")

    def update_intents_with_new_questions(self):
        try:
            if not self.new_questions['questions']:
                logger.debug("No new questions to process.")
                return

            manual_intent_map = {
                "what’s this random thing": "help",
                "what’s the minimum bid increment?": "bidding_overview",
                "i am new guide me": "help",
                "i am new to this": "registration_info",
                "is only regular auctions are there": "auction_type",
                "hllo": "greeting",
                "how do i set a reserve price for my auction listing?": "auction_management",
                "can i bid on multiple items at once in a sealed bid auction?": "bidding_overview",
                "is there a way to preview an auction before it goes live?": "preview",
                "how can i extend the duration of my auction if it’s about to end?": "auction_management",
                "what happens if no one meets the reserve price in a regular auction?": "auction_management",
                "can i offer a discount on the ‘buy it now’ price for specific bidders?": "auction_type",
                "how does auctionhub handle disputes over item condition after a sale?": "dispute",
                "is there a limit to how many auctions i can list at once as a seller?": "auction_management",
                "can i schedule an auction to start at a specific time and date?": "auction_management",
                "what’s the process for getting a refund if i overbid by mistake?": "refund",
                "does auctionhub offer escrow services for high-value items like luxury cars?": "escrow",
                "what’s the most expensive thing ever sold on auctionhub?": "auctions",
                "how can i withdraw my auction listing before it starts?": "help",
                "tell me about types of auctions": "auction_type",
                "should i need to complete the profile before diving into auctions": "registration_info",
                "profile": "account_management",
                "what this platform for": "platform_overview",
                "goodbye bro": "casual_farewell",
                "ok pal bye": "casual_farewell",
                "what’s the fee for selling an item?": "seller_fees"
            }

            for question in self.new_questions['questions']:
                if question['intent'] != "unknown":
                    continue
                text = question['text'].lower()
                if text in manual_intent_map:
                    question['intent'] = manual_intent_map[text]
                else:
                    text_lower = text
                    best_match = None
                    best_score = 0
                    for intent in self.intents['intents']:
                        for pattern in intent['patterns']:
                            distance = edit_distance(text_lower, pattern.lower())
                            similarity = 1 - (distance / max(len(text_lower), len(pattern)))
                            if similarity > best_score and similarity > 0.5:
                                best_score = similarity
                                best_match = intent['tag']
                    question['intent'] = best_match if best_score > 0.6 else "help"
                logger.debug(f"Assigned '{question['intent']}' to '{text}'")

            updated = False
            answered_questions = []
            for question in self.new_questions['questions']:
                if question['intent'] != "unknown" and question.get('answered', False):
                    intent_exists = False
                    for intent in self.intents['intents']:
                        if intent['tag'] == question['intent']:
                            intent_exists = True
                            if question['text'] not in intent['patterns']:
                                intent['patterns'].append(question['text'])
                                updated = True
                                logger.debug(f"Added pattern '{question['text']}' to '{intent['tag']}'")
                            break
                    if not intent_exists:
                        self.intents['intents'].append({
                            "tag": question['intent'],
                            "patterns": [question['text']],
                            "responses": []
                        })
                        updated = True
                        logger.debug(f"Created new intent '{question['intent']}' with pattern '{question['text']}'")
                    answered_questions.append(question['text'])

            if updated:
                with open(self.intents_file, 'w', encoding='utf-8') as f:
                    json.dump(self.intents, f, indent=2)
                logger.debug("Updated intents.json with new patterns")

            self.new_questions['questions'] = [
                q for q in self.new_questions['questions']
                if not q.get('answered', False) or q['text'] not in answered_questions
            ]
            self.save_new_questions()
            logger.debug("Updated intents with new questions")
        except Exception as e:
            logger.error(f"Error updating intents: {e}")

    def handle_admin_response(self, message, user_id, username):
        try:
            data = json.loads(message)
            question_text = data.get('question', '').strip()
            answer = data.get('answer', '').strip()
            intent = data.get('intent', '').strip()

            if not question_text or not answer:
                return f"Hey {username}, please provide both a question and an answer! 😊"

            if not intent:
                return f"Hey {username}, please provide or select an intent! 😊"

            # Validate intent tag
            if not re.match(r'^[a-z0-9_]+$', intent):
                return f"Hey {username}, intent tag must contain only lowercase letters, numbers, and underscores! 😞"

            # Check if intent already exists
            intent_exists = any(i['tag'] == intent for i in self.intents['intents'])

            # Store in answered_questions.json
            for q in self.new_questions['questions']:
                if q['text'].lower() == question_text.lower():
                    q['answer'] = answer
                    q['intent'] = intent
                    q['answered'] = True
                    q['answered_by'] = username
                    q['answered_at'] = str(datetime.datetime.now())
                    self.answered_questions['questions'].append({
                        "text": q['text'],
                        "answer": answer,
                        "intent": intent,
                        "answered_by": username,
                        "answered_at": str(datetime.datetime.now())
                    })
                    self.save_answered_questions()
                    break
            else:
                return f"Hey {username}, that question wasn't found in the pending list! 😞"

            # Update intents.json
            if not intent_exists:
                self.intents['intents'].append({
                    "tag": intent,
                    "patterns": [question_text],
                    "responses": []
                })
                logger.debug(f"Created new intent '{intent}' with pattern '{question_text}'")
            else:
                for i in self.intents['intents']:
                    if i['tag'] == intent:
                        if question_text not in i['patterns']:
                            i['patterns'].append(question_text)
                            logger.debug(f"Added pattern '{question_text}' to existing intent '{intent}'")
                        break

            with open(self.intents_file, 'w', encoding='utf-8') as f:
                json.dump(self.intents, f, indent=2)

            self.save_new_questions()
            self.update_intents_with_new_questions()
            logger.debug(f"Admin {username} answered question '{question_text}' with '{answer}' and intent '{intent}'")
            return f"Thanks, {username}! Your answer for '{question_text}' has been saved and added to the '{intent}' intent! 😄"
        except json.JSONDecodeError:
            logger.error("Invalid JSON in admin response")
            return f"Sorry, {username}, invalid response format! Please use the correct format. 😞"
        except Exception as e:
            logger.error(f"Error handling admin response: {e}")
            return f"Sorry, {username}, something went wrong: {str(e)}. 😞"

    def get_response(self, message, user_id="default", is_authenticated=False, username=None, is_admin=False):
        start_time = datetime.datetime.now()
        try:
            if isinstance(message, bytes):
                message = message.decode('utf-8', errors='replace')
            if not message.strip():
                return "Hey, you didn’t say anything! 😅 Toss me a question or just say hi to get started!"

            username = username if is_authenticated and username else "friend"
            logger.debug(
                f"Processing message: '{message}', username: {username}, user_id: {user_id}, authenticated: {is_authenticated}, admin: {is_admin}"
            )

            if not os.path.exists(self.intents_file):
                logger.error("intents.json missing")
                return f"Oops, {username}, my data’s playing hide-and-seek! 😅 Try again soon?"

            escalated = False
            if is_admin and message.startswith('{"question":'):
                return self.handle_admin_response(message, user_id, username)

            message_lower = message.lower()
            processed_message = self.preprocess(message)
            entities = self.extract_entities(message)
            history = self.load_conversation_history(user_id)

            response = None
            predicted_tag = None
            from_answered_questions = False

            # Check answered_questions.json with fuzzy matching
            matched_question, matched_answer, matched_intent, fuzzy_score = self.fuzzy_match_answered_questions(message, threshold=0.65)
            if matched_question and matched_answer and fuzzy_score >= 0.65:
                predicted_tag = matched_intent
                response = matched_answer
                from_answered_questions = True
                logger.debug(
                    f"Fuzzy matched answered question '{matched_question}' for input '{message}' with intent '{predicted_tag}', score: {fuzzy_score:.2f}"
                )
                # For non-authenticated users, limit the answer
                if not is_authenticated and predicted_tag not in ['greeting', 'casual_farewell', 'goodbye']:
                    response = f"Got a great answer for that, {username}! Sign up to unlock all the details about {predicted_tag.replace('_', ' ')}! 😎 Ready to join?"

            # Check intents.json for exact pattern match
            if not response:
                for intent in self.intents['intents']:
                    if message_lower in [p.lower() for p in intent['patterns']]:
                        predicted_tag = intent['tag']
                        responses = self.tag_to_responses.get(predicted_tag,
                                                              ["Something broke—let’s try again, {username}! 😅"])
                        if isinstance(responses, dict):
                            if predicted_tag == 'auction_type':
                                tokens = set(word_tokenize(message_lower))
                                if 'regular' in tokens:
                                    sub_tag = 'regular_auction'
                                elif 'sealed' in tokens:
                                    sub_tag = 'sealed_bid'
                                elif 'buy' in tokens or 'offer' in tokens:
                                    sub_tag = 'buy_it_now_make_offer'
                                else:
                                    sub_tag = 'general'
                                response = random.choice(responses.get(sub_tag, responses.get('general', [
                                    f"Hey {username}, we’ve got cool auction types! Sign up to learn about Regular, Sealed Bid, or Buy It Now! 😎"
                                    if not is_authenticated else
                                    f"Hey {username}, AuctionHub has Regular, Sealed Bid, and Buy It Now auctions. Want details on one? 😎"
                                ])))
                            else:
                                response = random.choice(
                                    responses.get(entities.get('category', 'general'), responses.get('general', [
                                        f"Oops, {username}, let’s try again! What’s up? 😅"
                                    ])))
                        else:
                            response = random.choice(responses)
                        logger.debug(f"Exact match found in intents.json for '{message}' with intent '{predicted_tag}'")
                        break

            if not response:
                if not self.tokenizer or not self.model:
                    logger.error("BERT tokenizer or model not loaded")
                    self.store_new_question(message)
                    escalated = True
                    return (f"Hmm, {username}, that’s a tricky one! 😅 I’ve sent it to the team—sign up to get the answer when it’s ready!"
                            if not is_authenticated else
                            f"Sorry, {username}, I’m stumped! 😅 I’ve passed your question to the team—ask about auctions while you wait!")

                inputs = self.tokenizer(
                    processed_message,
                    return_tensors='pt',
                    truncation=True,
                    padding=True,
                    max_length=64
                )

                predicted_tag = 'unknown'
                confidence = 0
                try:
                    with torch.no_grad():
                        outputs = self.model(**inputs)
                        probabilities = torch.softmax(outputs.logits, dim=1)[0]
                        predicted_intent_idx = torch.argmax(probabilities).item()
                        predicted_tag = self.label_map.get(predicted_intent_idx, 'unknown')
                        confidence = probabilities[predicted_intent_idx].item()
                    logger.debug(f"BERT Predicted: '{predicted_tag}', Confidence: {confidence:.2f}")
                except Exception as e:
                    logger.error(f"BERT inference failed: {e}")
                    predicted_tag = 'unknown'
                    confidence = 0

                is_new_user = any(phrase in message_lower for phrase in ['new', 'guide', 'beginner'])
                if is_new_user and predicted_tag not in ['help', 'registration_info', 'platform_overview']:
                    predicted_tag = 'help'
                    confidence = 0.8
                    logger.debug(f"Adjusted for new user: Predicted: 'help', Confidence: 0.8")

                is_affirm = self.is_affirmation(message)
                if is_affirm:
                    predicted_tag = 'affirmation'
                    confidence = 0.9
                    logger.debug(f"Detected affirmation, setting intent to 'affirmation'")

                if message_lower.startswith('hll') or message_lower in ['hlo', 'hllo']:
                    predicted_tag = 'greeting'
                    confidence = 0.9
                    logger.debug(f"Detected typo 'hllo', setting intent to 'greeting'")

                casual_intents = ['greeting', 'goodbye', 'casual_farewell', 'affirmation']
                if predicted_tag != 'unknown' and confidence >= 0.95 and predicted_tag in casual_intents:
                    logger.debug(f"Accepting high-confidence BERT prediction '{predicted_tag}' without pattern match")
                elif predicted_tag != 'unknown' and confidence >= 0.85:
                    if not self.pattern_match(message, predicted_tag):
                        fuzzy_tag, fuzzy_score = self.fuzzy_match(message)
                        if fuzzy_score >= 0.65 and fuzzy_tag == predicted_tag:
                            logger.debug(
                                f"Fuzzy match confirmed BERT prediction: '{predicted_tag}', score: {fuzzy_score:.2f}")
                        else:
                            predicted_tag = 'unknown'
                            confidence = 0
                            logger.debug(f"BERT prediction '{predicted_tag}' rejected, no fuzzy match support")
                    else:
                        logger.debug(f"BERT prediction '{predicted_tag}' accepted via pattern match")

                if predicted_tag == 'unknown' or confidence < 0.85:
                    fuzzy_tag, fuzzy_score = self.fuzzy_match(message)
                    if fuzzy_score >= 0.65:
                        predicted_tag = fuzzy_tag
                        confidence = fuzzy_score
                        logger.debug(f"Fuzzy match assigned intent: '{predicted_tag}', score: {fuzzy_score:.2f}")
                    else:
                        casual_farewell_keywords = ['bye', 'goodbye', 'later', 'peace', 'cya']
                        if any(keyword in message_lower for keyword in casual_farewell_keywords):
                            predicted_tag = 'casual_farewell'
                            response = random.choice([
                                f"See ya, {username}! Come back and sign up for auction fun! 😎",
                                f"Peace out, {username}! Join us to bid on cool stuff! 😄",
                                f"Later, {username}! Sign up to grab some epic deals! 👋"
                            ])
                            logger.debug(f"Detected casual farewell, assigned intent: 'casual_farewell'")
                        else:
                            self.store_new_question(message)
                            escalated = True
                            response = (f"Whoa, {username}, you’ve got me curious! 😅 Sign up to get that answered and explore auctions!"
                                        if not is_authenticated else
                                        f"Yikes, {username}, that’s a new one for me! 😅 I’ve sent it to the team—try asking about watches or bidding meanwhile!")
                            self.dialogue_state = 'escalated'
                            logger.debug(f"Escalated unrecognized question: '{message}'")
                else:
                    responses = self.tag_to_responses.get(predicted_tag, None)
                    if not responses:
                        logger.error(f"No responses found for intent '{predicted_tag}'")
                        if predicted_tag in casual_intents:
                            if predicted_tag == 'casual_farewell' or predicted_tag == 'goodbye':
                                response = random.choice([
                                    f"See ya, {username}! Come back and sign up for auction fun! 😎",
                                    f"Peace out, {username}! Join us to bid on cool stuff! 😄",
                                    f"Later, {username}! Sign up to grab some epic deals! 👋"
                                ])
                            else:
                                response = (f"Hey {username}, what’s the vibe? Sign up to dive into auctions! 😎"
                                            if not is_authenticated else
                                            f"Hey {username}, let’s chat—what’s up? Auctions or something else? 😎")
                        else:
                            self.store_new_question(message)
                            escalated = True
                            response = (f"Sorry, {username}, that’s a mystery for now! 😅 Sign up to get answers and bid on cool items!"
                                        if not is_authenticated else
                                        f"Oops, {username}, I’m stumped on that one! 😅 Try asking about auctions or categories while I pass this to the team!")
                            self.dialogue_state = 'escalated'
                    else:
                        if isinstance(responses, dict):
                            if predicted_tag == 'auction_type':
                                tokens = set(word_tokenize(message_lower))
                                if 'regular' in tokens:
                                    sub_tag = 'regular_auction'
                                elif 'sealed' in tokens:
                                    sub_tag = 'sealed_bid'
                                elif 'buy' in tokens or 'offer' in tokens:
                                    sub_tag = 'buy_it_now_make_offer'
                                else:
                                    sub_tag = 'general'
                                response = random.choice(responses.get(sub_tag, responses.get('general', [
                                    f"Hey {username}, we’ve got cool auction types! Sign up to learn about Regular, Sealed Bid, or Buy It Now! 😎"
                                    if not is_authenticated else
                                    f"Hey {username}, AuctionHub has Regular, Sealed Bid, and Buy It Now auctions. Want details on one? 😎"
                                ])))
                            else:
                                response = random.choice(
                                    responses.get(entities.get('category', 'general'), responses.get('general', [
                                        f"Oops, {username}, let’s try again! Sign up to explore auctions! 😅"
                                        if not is_authenticated else
                                        f"Oops, {username}, let’s try again! What’s on your mind? 😅"
                                    ])))
                        else:
                            response = random.choice(responses)

            if response is None or not isinstance(response, str):
                logger.error(f"Invalid response for intent '{predicted_tag}' and message '{message}': {response}")
                if predicted_tag in ['goodbye', 'casual_farewell']:
                    response = random.choice([
                        f"See ya, {username}! Come back and sign up for auction fun! 😎",
                        f"Peace out, {username}! Join us to bid on cool stuff! 😄",
                        f"Later, {username}! Sign up to grab some epic deals! 👋"
                    ])
                else:
                    response = (f"Sorry, {username}, I’m lost! 😅 Sign up to unlock answers and auctions!"
                                if not is_authenticated else
                                f"Sorry, {username}, I’m drawing a blank! 😅 Let’s talk auctions or categories—whatcha thinking?")
                    escalated = True

            # Apply intent-specific responses with context-aware refinements
            if not from_answered_questions:
                if predicted_tag in ['goodbye', 'casual_farewell'] and history:
                    recent_farewells = [h for h in history[:2] if h['intent'] in ['goodbye', 'casual_farewell']]
                    if len(recent_farewells) >= 2:
                        response = (f"Alright, {username}, you’re *really* dipping out? 😄 Sign up and come back for epic auctions!"
                                    if not is_authenticated else
                                    f"Okay, {username}, you’re *really* outta here? 😄 Pop back anytime for bidding action!")
                        logger.debug(f"Detected repeated farewell from history for user {user_id}")

                response = response.replace("friend", username) if isinstance(response, str) else response
                if predicted_tag == 'greeting':
                    response = (f"Hey {username}, welcome to AuctionHub! We’ve got awesome auctions for watches, cars, and more. Sign up to jump in—wanna hear more? 😎"
                                if not is_authenticated else
                                f"Yo {username}, great to see you! Ready to score some deals on AuctionHub? What’s up—watches, cars, or something else? 😎")
                    self.dialogue_state = 'greeting'
                elif predicted_tag == 'help':
                    response = (f"Yo {username}, AuctionHub’s where it’s at for unique finds! Sign up to get the full scoop on bidding or categories. Curious about anything? 😄"
                                if not is_authenticated else
                                f"Alright, {username}, I’m here for you! AuctionHub’s got luxury watches, cars, and more. Newbie? I can walk you through bidding or profile setup. What’s the plan? 🤝")
                    self.dialogue_state = 'help'
                elif predicted_tag == 'registration_info':
                    response = (f"Signing up’s your key to AuctionHub, {username}! It’s quick and unlocks all the auctions. Want a sneak peek at what’s up for grabs? 😎"
                                if not is_authenticated else
                                f"Good call, {username}! You’re ready to bid, but a complete profile makes bidding a breeze. Want steps to polish it or dive into auctions? 🚀")
                    self.dialogue_state = 'registration_info'
                elif predicted_tag == 'auctions':
                    category = entities.get('category', None)
                    response = (f"Whoa, {username}, our auctions are lit! Think {category if category else 'watches, cars, and jewelry'}. Sign up to check ‘em out—any faves? 😄"
                                if not is_authenticated else
                                f"Nice, {username}! We’ve got hot auctions for {category if category else 'luxury watches, cars, and more'}. Hit the ‘Auctions’ tab to browse. Got an item in mind? 🎉")
                    self.dialogue_state = 'auctions'
                elif predicted_tag == 'auction_type':
                    if not is_authenticated:
                        response = f"Auction types? Oh, we’ve got some cool ones, {username}! Sign up to learn about live bidding, secret offers, and instant buys! 😎"
                    # Authenticated users get the full response from the responses dict
                elif predicted_tag == 'bidding_overview':
                    response = (f"Bidding’s super exciting, {username}! You compete for awesome items, but you gotta sign up to join the action. Ready to get started? 😄"
                                if not is_authenticated else
                                f"Bidding’s your shot to snag treasures, {username}! In Regular auctions, you bid live; Sealed Bid’s a one-time offer; proxy bidding handles your max. Wanna try it out? 😎")
                    self.dialogue_state = 'bidding_overview'
                elif predicted_tag == 'seller_fees':
                    response = (f"Selling’s a vibe on AuctionHub, {username}! There’s a small fee, but sign up to see how easy it is to list your items! 😎"
                                if not is_authenticated else
                                f"Sellers pay a small commission on sales, {username}—no upfront costs! Check the ‘Sell’ section for rates. Got something to list? 😄")
                    self.dialogue_state = 'seller_fees'
                elif predicted_tag == 'account_management':
                    response = (f"Profile stuff, {username}? Sign up to manage your account and unlock bidding! Wanna know more about what’s possible? 😎"
                                if not is_authenticated else
                                f"Your profile’s your hub, {username}! Update info, payment methods, or bids in the ‘Profile’ section. Need help with settings? 🚀")
                    self.dialogue_state = 'account_management'
                elif predicted_tag == 'platform_overview':
                    response = (f"AuctionHub’s all about scoring unique items, {username}! From watches to cars, it’s a blast. Sign up to see what’s up! 😄"
                                if not is_authenticated else
                                f"AuctionHub’s your go-to for unique finds, {username}! Bid on luxury watches, cars, and more with live or instant options. Wanna explore a category? 😎")
                    self.dialogue_state = 'platform_overview'
                elif predicted_tag == 'affirmation':
                    if history and history[0].get('escalated', False):
                        prev_input = history[0]['input'].lower()
                        intent_suggestions = {
                            "tell me about types of auctions": ("auction_type",
                                                               f"Cool, {username}! You’re into auction types? Sign up to learn about live, secret, or instant buys! 😎"
                                                               if not is_authenticated else
                                                               f"Got it, {username}! You’re curious about auctions, right? Regular’s live bidding, Sealed Bid’s secret offers, and Buy It Now’s instant. Which one’s your vibe? 😎"),
                            "should i need to complete the profile before diving into auctions": ("registration_info",
                                                                                                 f"Nice, {username}! Profile questions? Sign up to set it up and start bidding! 😄"
                                                                                                 if not is_authenticated else
                                                                                                 f"Alright, {username}! Your profile’s ready, but completing it helps with bids. Want a quick guide? 🚀"),
                            "profile": ("account_management",
                                        f"Yo {username}, profile stuff? Sign up to manage your account! 😎"
                                        if not is_authenticated else
                                        f"Talking profiles, {username}? Manage yours in the ‘Profile’ section—update info or payments. Need a hand? 😄"),
                            "what is regular,sealedand buy it now auctions": ("auction_type",
                                                                             f"Auction types, {username}? They’re awesome! Sign up to dive into the details! 😎"
                                                                             if not is_authenticated else
                                                                             f"Hey {username}, auction types rock! Regular’s live, Sealed Bid’s a one-shot offer, Buy It Now’s instant. Wanna dig deeper? 😎"),
                            "what is regular,": ("auction_type",
                                                 f"Regular auctions, {username}? They’re exciting! Sign up to see how they work! 😄"
                                                 if not is_authenticated else
                                                 f"Regular auctions, {username}? It’s live bidding where the highest offer wins. Wanna check one out? 🚀")
                        }
                        for query, (suggested_tag, suggested_response) in intent_suggestions.items():
                            if query in prev_input:
                                predicted_tag = suggested_tag
                                response = suggested_response
                                self.dialogue_state = predicted_tag
                                logger.debug(
                                    f"Post-affirmation intent suggestion: '{predicted_tag}' for escalated query '{prev_input}'")
                                break
                        else:
                            response = (f"Got it, {username}! Your question’s with the team—sign up to see their answer and explore auctions! 😎"
                                        if not is_authenticated else
                                        f"Alright, {username}! The team’s on your question. Wanna browse watches or ask something else? 😄")
                            self.dialogue_state = 'escalated'
                    else:
                        if history:
                            prev_intent = history[0]['intent']
                            prev_category = history[0].get('entities', {}).get('category', None)
                            if prev_intent == 'greeting':
                                response = (f"Cool, {username}! Sign up to dive into auctions—wanna hear about watches or cars? 😎"
                                            if not is_authenticated else
                                            f"Sweet, {username}! Let’s roll—wanna browse auctions or learn about bidding? 😎")
                            elif prev_intent == 'auctions':
                                response = (f"Auctions are fire, {username}! Sign up to see {prev_category if prev_category else 'watches and cars'}! 😄"
                                            if not is_authenticated else
                                            f"Love it, {username}! Check the ‘Auctions’ tab for {prev_category if prev_category else 'watches, cars, and more'}. Got a target? 🎉")
                            elif prev_intent == 'categories':
                                response = (f"Categories galore, {username}! Sign up to explore {prev_category if prev_category else 'watches, cars, jewelry'}! 😎"
                                            if not is_authenticated else
                                            f"Right on, {username}! Pick from luxury watches, cars, or jewelry. What’s your jam? 😊")
                            elif prev_intent == 'help':
                                response = (f"Need a hand, {username}? Sign up for the full AuctionHub guide! 😄"
                                            if not is_authenticated else
                                            f"Alright, {username}! What’s next—bidding tips or profile help? I’m all text! 🤝")
                            elif prev_intent == 'registration_info':
                                response = (f"Signing up’s easy, {username}! Join to unlock bidding—wanna know more? 😎"
                                            if not is_authenticated else
                                            f"Got it, {username}! Ready to bid or wanna tweak your profile first? 🚀")
                            elif prev_intent in ['auction_type', 'bidding_overview', 'seller_fees', 'account_management', 'platform_overview']:
                                response = (f"More on {prev_intent.replace('_', ' ')}, {username}? Sign up to unlock all the details! 😎"
                                            if not is_authenticated else
                                            f"Cool, {username}! Let’s dive deeper into {prev_intent.replace('_', ' ')}—what’s your next question? 😄")
                        else:
                            response = (f"Alright, {username}! Sign up to explore auctions or ask me anything! 😎"
                                        if not is_authenticated else
                                        f"Cool, {username}! What’s next—auctions, bidding, or something else? 😎")
                        self.dialogue_state = 'affirmation'

            if is_authenticated:
                self.save_conversation(user_id, message, response, predicted_tag or 'unknown', entities, escalated)

            if predicted_tag and predicted_tag not in ['unknown', 'greeting', 'help', 'registration_info', 'auctions',
                                                      'affirmation', 'casual_farewell', 'goodbye']:
                self.dialogue_state = predicted_tag

            response = response.encode('utf-8', errors='replace').decode('utf-8')
            processing_time = (datetime.datetime.now() - start_time).total_seconds()
            logger.debug(f"Response: {response}, Processing time: {processing_time}s")
            return response
        except Exception as e:
            logger.error(f"Error in get_response: {e}")
            return (f"Oops, {username}, something’s off! 😅 Sign up and try again!"
                    if not is_authenticated else
                    f"Yikes, {username}, something broke! 😅 Try again—whatcha wanna talk about?")

if __name__ == "__main__":
    chatbot = Chatbot()
    chatbot.update_intents_with_new_questions()
    test_cases = [
        ("1008", "hi", True, "ujjwal", False),
        ("1008", "tell me about types of auctions", True, "ujjwal", False),
        ("1008", "yes", True, "ujjwal", False),
        ("1008", "profile", True, "ujjwal", False),
        ("1008", "should i need to complete the profile before diving into auctions", True, "ujjwal", False),
        ("1008", "ok", True, "ujjwal", False),
        ("1008", "what is bidding", True, "ujjwal", False),
        ("1008", "how many auctions do you have", True, "ujjwal", False),
        ("1010", "what this platform for", True, "sujith", False),
        ("1010", "goodbye bro", True, "sujith", False),
        ("1010", "ok pal bye", True, "sujith", False),
        ("1008", "What’s the fee for selling an item?", True, "ujjwal", False),
        ("1011", "hi", False, None, False),
        ("1011", "tell me about types of auctions", False, None, False),
        ("1011", "what is bidding", False, None, False),
        ("1011", "goodbye", False, None, False)
    ]
    for user_id, input_text, auth, username, is_admin in test_cases:
        print(
            f"User: {user_id}, Input: {input_text}, Auth: {auth}, Username: {username}, Admin: {is_admin} -> {chatbot.get_response(input_text, user_id=user_id, is_authenticated=auth, username=username, is_admin=is_admin)}")