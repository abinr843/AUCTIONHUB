import nltk
from nltk.tokenize import word_tokenize
from nltk.stem import WordNetLemmatizer
import json
import torch
from transformers import BertTokenizer, BertForSequenceClassification, Trainer, TrainingArguments
import os
from datasets import Dataset
import numpy as np
from sklearn.metrics import accuracy_score, precision_recall_fscore_support
import random
import spacy

# Download NLTK resources
nltk.download('punkt')
nltk.download('wordnet')
nltk.download('stopwords')

# Load spaCy for entity tagging
nlp = spacy.load("en_core_web_sm")

def preprocess_text(text, lemmatizer):
    tokens = word_tokenize(text.lower())
    tokens = [lemmatizer.lemmatize(token) for token in tokens if token.isalnum()]
    return ' '.join(tokens)

def extract_entities(text):
    """Extract auction-specific entities using spaCy."""
    doc = nlp(text)
    entities = []
    for ent in doc:
        if ent.text.lower() in ["regular auction", "regular auctions", "sealed bid", "buy it now", "make offer"]:
            entities.append(("auction_type", ent.text.lower()))
        elif ent.text.lower() in ["luxury watches", "rare collectibles", "luxury cars", "jewelry & diamonds"]:
            entities.append(("category", ent.text.lower()))
    return entities

def compute_metrics(pred):
    labels = pred.label_ids
    preds = pred.predictions.argmax(-1)
    precision, recall, f1, _ = precision_recall_fscore_support(labels, preds, average='weighted')
    acc = accuracy_score(labels, preds)
    return {
        'accuracy': acc,
        'f1': f1,
        'precision': precision,
        'recall': recall
    }

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

def augment_data(texts, labels, label_map, intents, multiplier=7):
    augmented_texts = texts.copy()
    augmented_labels = labels.copy()
    augmented_entities = [[] for _ in texts]

    label_to_patterns = {}
    for tag, idx in label_map.items():
        label_to_patterns[idx] = []
        for intent in intents['intents']:
            if intent['tag'] == tag:
                label_to_patterns[idx].extend(intent['patterns'])

    variations = {
        "auction": ["auctions", "aution", "aucion"],
        "regular": ["reguler", "reglar"],
        "bid": ["bidding", "bidd"],
        "only": ["just", "solely"],
        "admin": ["administrator", "admim"]
    }

    for label_idx in set(labels):
        patterns = label_to_patterns[label_idx]
        question_patterns = [p for p in patterns if p.lower().startswith(('is ', 'are ', 'do ', 'what ', 'how ', 'when '))]
        declarative_patterns = [p for p in patterns if not p.lower().startswith(('is ', 'are ', 'do ', 'what ', 'how ', 'when '))]

        for pattern in question_patterns:
            entities = extract_entities(pattern)
            for _ in range(multiplier):
                words = pattern.lower().split()
                if len(words) < 2:
                    continue
                new_pattern = [words[0]]
                if 'only' in words or 'just' in words:
                    new_pattern.append(random.choice(['only', 'just']))
                for i in range(1, len(words)):
                    if words[i] in ('only', 'just'):
                        continue
                    if random.random() > 0.4:
                        new_pattern.append(words[i])
                    else:
                        for key, var_list in variations.items():
                            if words[i] == key:
                                new_pattern.append(random.choice(var_list))
                                break
                        else:
                            new_pattern.append(words[i])
                if random.random() < 0.3:
                    new_pattern.append(random.choice(['there', 'available', 'here']))
                new_text = ' '.join(new_pattern)
                if new_text not in augmented_texts:
                    augmented_texts.append(new_text)
                    augmented_labels.append(label_idx)
                    augmented_entities.append(entities)

        words_by_position = {}
        for pattern in declarative_patterns:
            words = pattern.lower().split()
            for i, word in enumerate(words):
                if i not in words_by_position:
                    words_by_position[i] = []
                if word not in words_by_position[i]:
                    words_by_position[i].append(word)

        for _ in range(multiplier * len(declarative_patterns)):
            if len(words_by_position) < 2:
                continue
            positions = sorted(list(words_by_position.keys()))
            max_len = random.randint(2, min(len(positions), 6))
            selected_positions = sorted(random.sample(positions, max_len))
            new_pattern = []
            for pos in selected_positions:
                if words_by_position[pos]:
                    new_pattern.append(random.choice(words_by_position[pos]))
            if new_pattern:
                new_text = ' '.join(new_pattern)
                if new_text not in augmented_texts:
                    entities = extract_entities(new_text)
                    augmented_texts.append(new_text)
                    augmented_labels.append(label_idx)
                    augmented_entities.append(entities)

        if len(patterns) >= 2 and random.random() < 0.2:
            for _ in range(multiplier // 2):
                p1 = random.choice(patterns)
                p2 = random.choice(patterns)
                new_text = f"{p1} and {p2}"
                entities = extract_entities(new_text)
                if new_text not in augmented_texts:
                    augmented_texts.append(new_text)
                    augmented_labels.append(label_idx)
                    augmented_entities.append(entities)

    return augmented_texts, augmented_labels, augmented_entities

def train_chatbot():
    lemmatizer = WordNetLemmatizer()
    tokenizer = BertTokenizer.from_pretrained('bert-base-uncased')
    intents_file = os.path.join(os.path.dirname(__file__), 'intents.json')
    new_questions_file = os.path.join(os.path.dirname(__file__), 'new_questions.json')
    history_file = os.path.join(os.path.dirname(__file__), 'conversation_history.json')

    # Load intents
    with open(intents_file, 'r', encoding='utf-8') as f:
        intents = json.load(f)
        print("Loaded intents with tags:", [intent['tag'] for intent in intents['intents']])

    # Load new questions
    new_questions = {"questions": []}
    try:
        with open(new_questions_file, 'r', encoding='utf-8') as f:
            new_questions = json.load(f)
            print("Loaded new questions:", [q['text'] for q in new_questions['questions']])
    except (FileNotFoundError, json.JSONDecodeError):
        print("No new_questions.json found or empty, proceeding with intents only")

    # Load conversation history
    history = load_conversation_history(history_file)

    # Prepare dataset
    texts = []
    labels = []
    entities_list = []
    label_map = {intent['tag']: idx for idx, intent in enumerate(intents['intents'])}
    tag_map = {idx: intent['tag'] for idx, intent in enumerate(intents['intents'])}

    # Add patterns from intents.json
    for intent in intents['intents']:
        print(f"Intent {intent['tag']} has {len(intent['patterns'])} patterns")
        for pattern in intent['patterns']:
            processed_pattern = preprocess_text(pattern, lemmatizer)
            entities = extract_entities(pattern)
            texts.append(processed_pattern)
            labels.append(label_map[intent['tag']])
            entities_list.append(entities)
            if "random thing" in pattern.lower() or "minimum bid increment" in pattern.lower():
                print(f"Found pattern: {pattern}, Intent: {intent['tag']}, Entities: {entities}")

    # Add answered questions from new_questions.json
    for question in new_questions['questions']:
        if question.get('answered', False) and question.get('answer') and question['intent'] != "unknown":
            processed_text = preprocess_text(question['text'], lemmatizer)
            entities = extract_entities(question['text'])
            if question['intent'] not in label_map:
                new_idx = len(label_map)
                label_map[question['intent']] = new_idx
                tag_map[new_idx] = question['intent']
                intents['intents'].append({
                    "tag": question['intent'],
                    "patterns": [question['text']],
                    "responses": [question['answer']]
                })
                print(f"Added new intent {question['intent']} from new_questions")
            texts.append(processed_text)
            labels.append(label_map[question['intent']])
            entities_list.append(entities)
            print(f"Added answered question: {question['text']}, Intent: {question['intent']}")

    # Add historical interactions from conversation_history.json
    for session_id, interactions in history.items():
        for interaction in interactions:
            input_text = interaction.get('input', '')
            intent = interaction.get('intent', 'unknown')
            entities = interaction.get('entities', [])
            if intent in label_map and input_text:
                processed_text = preprocess_text(input_text, lemmatizer)
                texts.append(processed_text)
                labels.append(label_map[intent])
                entities_list.append(entities)
                print(f"Added historical interaction: {input_text}, Intent: {intent}, Entities: {entities}")
            else:
                print(f"Skipped historical interaction: {input_text}, Intent: {intent} (not in label_map)")

    # Add escalation_status intent if not present
    escalation_patterns = [
        "when will i get the answer",
        "when will the admin reply",
        "how long for admin response",
        "status of my question",
        "when will my question be answered",
        "how soon will admin answer"
    ]
    if 'escalation_status' not in label_map:
        new_idx = len(label_map)
        label_map['escalation_status'] = new_idx
        tag_map[new_idx] = 'escalation_status'
        intents['intents'].append({
            "tag": "escalation_status",
            "patterns": escalation_patterns,
            "responses": [
                "Your question is with the admin! They usually respond within 24-48 hours. Want to explore auctions like watches or cars while you wait? 😊"
            ]
        })
        print("Added escalation_status intent")
    for pattern in escalation_patterns:
        processed_pattern = preprocess_text(pattern, lemmatizer)
        entities = extract_entities(pattern)
        texts.append(processed_pattern)
        labels.append(label_map['escalation_status'])
        entities_list.append(entities)
        print(f"Added escalation pattern: {pattern}")

    # Apply data augmentation
    print("Original dataset size:", len(texts))
    aug_texts, aug_labels, aug_entities = augment_data(texts, labels, label_map, intents)
    print("Augmented dataset size:", len(aug_texts))

    # Convert to Hugging Face Dataset
    dataset = Dataset.from_dict({'text': aug_texts, 'label': aug_labels, 'entities': aug_entities})

    def tokenize_function(examples):
        tokenized = tokenizer(
            examples['text'],
            padding='max_length',
            truncation=True,
            max_length=64
        )
        tokenized['entities'] = examples['entities']
        return tokenized

    tokenized_dataset = dataset.map(tokenize_function, batched=True)
    tokenized_dataset.set_format('torch', columns=['input_ids', 'attention_mask', 'label'])

    # Split dataset
    tokenized_dataset = tokenized_dataset.shuffle(seed=42)
    train_size = int(0.9 * len(tokenized_dataset))
    train_dataset = tokenized_dataset.select(range(train_size))
    eval_dataset = tokenized_dataset.select(range(train_size, len(tokenized_dataset)))

    # Initialize model
    model = BertForSequenceClassification.from_pretrained(
        'bert-base-uncased',
        num_labels=len(label_map)
    )

    # Training arguments
    training_args = TrainingArguments(
        output_dir='./chatbot_bert_model',
        num_train_epochs=12,
        per_device_train_batch_size=16,
        per_device_eval_batch_size=16,
        warmup_ratio=0.1,
        weight_decay=0.01,
        learning_rate=3e-5,
        logging_dir='./logs',
        logging_steps=10,
        evaluation_strategy='epoch',
        save_strategy='epoch',
        load_best_model_at_end=True,
        metric_for_best_model='f1',
        save_total_limit=2,
    )

    # Trainer
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        compute_metrics=compute_metrics,
    )

    # Train
    print("Starting training...")
    trainer.train()

    # Evaluate
    eval_results = trainer.evaluate()
    print(f"Evaluation results: {eval_results}")

    # Save model and tokenizer
    model_dir = os.path.join(os.path.dirname(__file__), 'chatbot_bert_model')
    os.makedirs(model_dir, exist_ok=True)
    model.save_pretrained(model_dir)
    tokenizer.save_pretrained(model_dir)

    # Save label mapping and entity metadata
    with open(os.path.join(model_dir, 'label_map.json'), 'w') as f:
        json.dump(tag_map, f, indent=2)
    with open(os.path.join(model_dir, 'entity_map.json'), 'w') as f:
        entity_map = {
            "auction_type": ["regular auction", "regular auctions", "sealed bid", "buy it now", "make offer"],
            "category": ["luxury watches", "rare collectibles", "luxury cars", "jewelry & diamonds"]
        }
        json.dump(entity_map, f, indent=2)

    print("Chatbot training completed. BERT model, label map, and entity map saved.")

    # Test model
    def test_intent_recognition(text):
        processed_text = preprocess_text(text, lemmatizer)
        entities = extract_entities(text)
        inputs = tokenizer(processed_text, return_tensors="pt", padding=True, truncation=True)
        outputs = model(**inputs)
        probabilities = torch.nn.functional.softmax(outputs.logits, dim=-1)
        predicted_class = torch.argmax(probabilities, dim=-1).item()
        confidence = probabilities[0][predicted_class].item()
        predicted_tag = tag_map[predicted_class]
        return predicted_tag, confidence, entities

    test_examples = [
        "hi",
        "what auctions are available",
        "how do I bid",
        "goodbye",
        "what’s this random thing",
        "What’s the minimum bid increment?",
        "is only regular auctions are there",
        "are there luxury watches and how to bid",
        "is reguler auctions only available",
        "when will i get the answer",
        "how soon will admin answer",
        "feels something off",
        "what’s good"
    ]

    print("\nTesting model on examples:")
    for example in test_examples:
        tag, confidence, entities = test_intent_recognition(example)
        print(f"Input: '{example}' → Intent: '{tag}' (Confidence: {confidence:.2f}), Entities: {entities}")

if __name__ == "__main__":
    train_chatbot()