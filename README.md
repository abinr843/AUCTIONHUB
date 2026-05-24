# ZinCo Auction Platform (AuctionHub)

## 1. Project Abstract
Welcome to the **ZinCo Auction Platform** (AuctionHub)! This application is a high-performance, feature-rich web marketplace built upon a **Hybrid Python/Django 5.1.4 and MySQL** architecture. It is designed to handle high-frequency bidding, automated lifecycle management, and intelligent user interactions.

### Unique Architectural Choices
* **Hybrid ORM & Raw SQL Architecture:** To achieve both structural integrity and maximum query performance, the application leverages Django ORM for strict schema management, constraint enforcement, and user authentication, while complex transactional operations (like background automation and concurrency-heavy bid placements) rely on highly optimized, explicitly parameterized raw SQL wrapped in `transaction.atomic()` contexts.
* **Intelligent Chatbot Integration:** Embedded inside the core platform is an advanced NLP Chatbot powered by **BERT** (for rapid Intent Classification) and **T5** (for generative Fallback responses). Supported by NLTK and spaCy, it handles fuzzy pattern matching and supports an iterative Human-in-the-Loop mechanism for escalating unknown queries to admins.
* **Advanced Bidding Ecosystem:** Natively supports regular auctions, sealed-bid mechanisms, and buy-it-now offers, seamlessly tied to an internal wallet credit mechanism.
* **Comprehensive Notification Stack:** Dynamic, real-time in-app dashboard alerts coupled with asynchronous email dispatches using Django's SMTP backend.

---

## 2. Infrastructure Automation (`scheduler.py`)
This system runs an extensive background multi-threaded automation daemon (`scheduler.py`) to orchestrate the lifecycle of auctions, bids, and user states without manual admin intervention.

### Core Automation Pipelines:
* **Winner Selection (Regular & Sealed Bids):** The engine constantly monitors ended auctions. Utilizing raw `SELECT ... FOR UPDATE` row-locking, it automatically computes highest bids, validates them against reserve prices, binds winners into final `Orders`, and issues victory/loss notification blasts.
* **Invoice Generation Strategy:** The system automatically sweeps confirmed orders and dynamically generates unique UUID-based `Invoices` to buyers with strict expiration timestamps.
* **Overdue Analytics & Late Fees:** Periodically sweeps unpaid invoices against their due dates. If an invoice transitions to an `Overdue` state, a recursive 5% mathematical penalty is appended to the order and an alert is fired.
* **VIP User Lifecycle Management:** Actively monitors the `premium_end_date` of VIP users. It fires automated warning emails 2 days prior to expiration. Upon expiration, it automatically revokes privileges and resets the user's platform visibility.
* **Global Sync:** Triggers global platform alerts whenever newly published auctions are detected.

---

## 3. Developer Environment Setup

Because this application contains strict security footprints, massive Deep Learning weights, and live transactional user logs, we actively ignore various internal configurations via `.gitignore`. 

**If you are cloning this repository, you must manually construct the following elements:**

### A. Environment Config (`settings.py` / `.env`)
* By default, `online_auction/settings.py` is excluded or stubbed since it contains hardcoded configuration maps (like MySQL root credentials and SMTP app passwords).
* **To Fix:** Create a local `settings.py` mapped to your local MySQL server instance (`root` / `mysql` by default for development) and securely supply the Django `SECRET_KEY`.

### B. Database Requirements
* Ensure a MySQL database named `auctions` exists on `localhost:3306`.
* Run `python manage.py makemigrations core` and `python manage.py migrate` to map the 30+ relational data structures. 
* *Note:* While legacy SQL dumps (`auctionss.sql`) exist, the platform relies on the Django migration ecosystem to ensure structural constraints (like `UserOTP.created_at` NOT NULL fields) are actively maintained.

### C. File Storage & Media
* User-uploaded media, cached profiles, and KYC documents are ignored.
* **To Fix:** Simply recreate the `online_auction/media/` tree to satisfy Django's `MEDIA_ROOT`. 

### D. Artificial Intelligence Models
* Pushing multi-gigabyte models into Git is forbidden. The `/core/chatbot_bert_model/` and `/core/chatbot_t5_model/` paths are `.gitignore`d.
* **To Fix:** You must generate, fine-tune, or pull the PyTorch weights (`.bin` / `.safetensors`) and tokenizer assets manually into those paths or use the provided training fallback scripts to regenerate them locally.

### E. JSON Transaction Logs
* The AI Assistant's state and context JSON logs are highly dynamic and ignored.
* **To Fix:** The bot is self-healing. Sending the first `POST` request to the chatbot endpoint will safely regenerate clean baseline states for `users.json`, `sessions.json`, `conversation_history.json`, and `new_questions.json`.
