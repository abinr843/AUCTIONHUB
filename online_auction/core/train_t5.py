import json
import os
import random
from transformers import T5Tokenizer, T5ForConditionalGeneration, Trainer, TrainingArguments
from datasets import Dataset

def load_intents(intents_file):
    with open(intents_file, 'r', encoding='utf-8') as f:
        return json.load(f)

def load_sessions(sessions_file):
    try:
        with open(sessions_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        print("Warning: sessions.json not found or invalid. Using default usernames.")
        return {"session_id_123": "sujith", "session_id_456": "alice"}

def load_conversation_history(history_file):
    """Load conversation history from conversation_history.json."""
    try:
        with open(history_file, 'r', encoding='utf-8') as f:
            history = json.load(f)
            print("Loaded conversation history with sessions:", list(history.keys()))
            return history
    except (FileNotFoundError, json.JSONDecodeError):
        print("Warning: conversation_history.json not found or invalid. Proceeding without history.")
        return {}

def create_dialogue_dataset(intents, sessions, history):
    dialogues = []
    session_ids = list(sessions.keys())
    default_username = "friend"

    # Add dialogues from intents.json
    for intent in intents['intents']:
        tag = intent['tag']
        for pattern in intent['patterns']:
            session_id = random.choice(session_ids) if session_ids else "default"
            username = sessions.get(session_id, default_username)

            # Check if responses is a list of dictionaries with sub-tags or a list of strings
            if isinstance(intent['responses'], list) and all(isinstance(sub, dict) and 'tag' in sub and 'responses' in sub for sub in intent['responses']):
                for sub in intent['responses']:
                    for resp in sub['responses']:
                        dialogues.append({
                            "prompt": f"User: {pattern}\nSession ID: {session_id}\nGenerate a friendly, personalized response for AuctionHub:",
                            "response": resp.replace("friend", username)
                        })
            else:
                # Handle case where responses is a list of strings or a single string
                responses = intent['responses'] if isinstance(intent['responses'], list) else [intent['responses']]
                for resp in responses:
                    dialogues.append({
                        "prompt": f"User: {pattern}\nSession ID: {session_id}\nGenerate a friendly, personalized response for AuctionHub:",
                        "response": resp.replace("friend", username)
                    })

    # Add dialogues from conversation_history.json
    for session_id, interactions in history.items():
        username = sessions.get(session_id, default_username)
        for i, interaction in enumerate(interactions):
            input_text = interaction.get('input', '')
            response = interaction.get('response', '')
            intent = interaction.get('intent', 'unknown')
            if input_text and response and intent != 'unknown':
                # Build context from up to 2 previous interactions
                context = []
                for j in range(max(0, i-2), i):
                    prev = interactions[j]
                    context.append(f"User: {prev['input']} Bot: {prev['response']}")
                context_str = "\n".join(context) if context else ""
                prompt = f"User: {input_text}\nContext: {context_str}\nSession ID: {session_id}\nGenerate a friendly, personalized response for AuctionHub:"
                dialogues.append({
                    "prompt": prompt,
                    "response": response.replace("friend", username)
                })
                print(f"Added historical dialogue: {input_text}, Intent: {intent}, Username: {username}")

    # Add example dialogues with context
    dialogues.extend([
        {
            "prompt": f"User: what’s the difference?\nContext: User: is only regular auctions are there Bot: Nope, we’ve got variety! AuctionHub offers Regular auctions for live bidding, Sealed Bid for private offers, and Buy It Now or Make Offer for quick deals. Which one sounds fun? 😄\nSession ID: session_id_123\nGenerate a friendly, personalized response for AuctionHub:",
            "response": f"Hey sujith, since we talked auctions, Regular ones are live bidding, while Sealed Bid keeps your offer private. Want more on one? 😄"
        },
        {
            "prompt": f"User: yeah\nContext: User: are there luxury watches Bot: We’ve got luxury watches in Categories! Want to check some hot listings? 🎉\nSession ID: session_id_456\nGenerate a friendly, personalized response for AuctionHub:",
            "response": f"Sweet, alice! Want to check out some luxury watch listings? 😎"
        },
        {
            "prompt": f"User: how’s bidding on watches?\nContext: User: what’s good Bot: Yo, just chillin’ like a villain! What’s the vibe with you—ready to score some auction deals? 😎\nSession ID: session_id_123\nGenerate a friendly, personalized response for AuctionHub:",
            "response": f"Hey sujith, bidding on luxury watches is a thrill! Pick a Regular auction and place your offer—highest wins. Want to see some listings? 😎"
        }
    ])

    print(f"Created {len(dialogues)} dialogues with usernames from sessions: {list(sessions.values())}")
    return dialogues

def train_t5():
    intents_file = os.path.join(os.path.dirname(__file__), 'intents.json')
    sessions_file = os.path.join(os.path.dirname(__file__), 'sessions.json')
    history_file = os.path.join(os.path.dirname(__file__), 'conversation_history.json')

    intents = load_intents(intents_file)
    sessions = load_sessions(sessions_file)
    history = load_conversation_history(history_file)
    dialogues = create_dialogue_dataset(intents, sessions, history)

    dataset = Dataset.from_list(dialogues)

    tokenizer = T5Tokenizer.from_pretrained("t5-small")

    def tokenize_function(examples):
        inputs = tokenizer(
            examples['prompt'],
            padding='max_length',
            truncation=True,
            max_length=512,
            return_tensors="pt"
        )
        labels = tokenizer(
            examples['response'],
            padding='max_length',
            truncation=True,
            max_length=128,
            return_tensors="pt"
        )
        inputs['labels'] = labels['input_ids']
        return inputs

    tokenized_dataset = dataset.map(tokenize_function, batched=True)
    tokenized_dataset.set_format('torch', columns=['input_ids', 'attention_mask', 'labels'])

    train_size = int(0.8 * len(tokenized_dataset))
    train_dataset = tokenized_dataset.select(range(train_size))
    eval_dataset = tokenized_dataset.select(range(train_size, len(tokenized_dataset)))

    model = T5ForConditionalGeneration.from_pretrained("t5-small")

    training_args = TrainingArguments(
        output_dir='./chatbot_t5_model',
        num_train_epochs=3,
        per_device_train_batch_size=4,
        per_device_eval_batch_size=4,
        warmup_steps=100,
        weight_decay=0.01,
        logging_dir='./logs',
        logging_steps=10,
        evaluation_strategy='epoch',
        save_strategy='epoch',
        load_best_model_at_end=True
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset
    )


    print("Starting T5 training...")
    trainer.train()

    model.save_pretrained('./chatbot_t5_model')
    tokenizer.save_pretrained('./chatbot_t5_model')
    print("T5 model saved to ./chatbot_t5_model")

if __name__ == "__main__":
    train_t5()