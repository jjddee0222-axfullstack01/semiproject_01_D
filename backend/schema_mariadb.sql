-- PIN POINT REVIEW : MariaDB 10.5+ DDL (backend/models.py 에서 자동 생성, 참고용)
-- 실제 테이블은 서버 시작 시 자동 생성됩니다. 계정·DB 생성은 setup_mariadb.sql 참고
-- 버전 기록·변경은 Alembic: cd backend → python -m alembic upgrade head  (README 참고)

CREATE TABLE users (
	id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
	email VARCHAR(255) NOT NULL, 
	password_hash VARCHAR(255) NOT NULL, 
	name VARCHAR(50) NOT NULL, 
	mall_name VARCHAR(100) NOT NULL, 
	mall_platform ENUM('NAVER','COUPANG','OWN','ETC') NOT NULL, 
	business_number CHAR(10) NOT NULL, 
	status ENUM('ACTIVE','WITHDRAWN') NOT NULL DEFAULT 'ACTIVE', 
	created_at DATETIME NOT NULL DEFAULT now(), 
	withdrawn_at DATETIME, 
	PRIMARY KEY (id), 
	UNIQUE (email), 
	UNIQUE (business_number)
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_unicode_ci;

CREATE TABLE ingest_logs (
	id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
	batch_name VARCHAR(255) NOT NULL, 
	total_count INTEGER NOT NULL DEFAULT '0', 
	duplicate_count INTEGER NOT NULL DEFAULT '0', 
	missing_count INTEGER NOT NULL DEFAULT '0', 
	run_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id)
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_unicode_ci;

CREATE TABLE keywords (
	id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
	word VARCHAR(100) NOT NULL, 
	polarity ENUM('POS','NEG','NEU') NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (word)
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_unicode_ci;

CREATE INDEX ix_keywords_polarity ON keywords (polarity);

CREATE TABLE sessions (
	id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
	user_id BIGINT UNSIGNED NOT NULL, 
	session_token_hash CHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL DEFAULT now(), 
	expires_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	UNIQUE (session_token_hash)
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_unicode_ci;

CREATE INDEX ix_sessions_user_id ON sessions (user_id);

CREATE INDEX ix_sessions_expires_at ON sessions (expires_at);

CREATE TABLE products (
	id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
	seller_id BIGINT UNSIGNED NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	category VARCHAR(100), 
	description TEXT, 
	description_embedding JSON, 
	created_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id), 
	FOREIGN KEY(seller_id) REFERENCES users (id) ON DELETE CASCADE
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_unicode_ci;

CREATE INDEX ix_products_seller_category ON products (seller_id, category);

CREATE TABLE risk_keywords (
	id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
	seller_id BIGINT UNSIGNED NOT NULL, 
	word VARCHAR(100) NOT NULL, 
	weight TINYINT UNSIGNED NOT NULL DEFAULT '1', 
	created_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id), 
	CONSTRAINT uq_risk_keywords_seller_word UNIQUE (seller_id, word), 
	FOREIGN KEY(seller_id) REFERENCES users (id) ON DELETE CASCADE
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_unicode_ci;

CREATE TABLE shop_monthly_stats (
	seller_id BIGINT UNSIGNED NOT NULL, 
	month DATE NOT NULL, 
	visitors INTEGER NOT NULL DEFAULT '0', 
	buyers INTEGER NOT NULL DEFAULT '0', 
	PRIMARY KEY (seller_id, month), 
	FOREIGN KEY(seller_id) REFERENCES users (id) ON DELETE CASCADE
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_unicode_ci;

CREATE TABLE feedbacks (
	id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
	user_id BIGINT UNSIGNED, 
	complaint TEXT NOT NULL, 
	suggestion TEXT NOT NULL, 
	created_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE SET NULL
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_unicode_ci;

CREATE TABLE reviews (
	id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
	product_id BIGINT UNSIGNED NOT NULL, 
	reviewer_name VARCHAR(50), 
	rating TINYINT UNSIGNED NOT NULL, 
	content_raw TEXT NOT NULL, 
	content_clean TEXT, 
	content_embedding JSON, 
	reviewed_at DATE NOT NULL, 
	status ENUM('VISIBLE','BLINDED') NOT NULL DEFAULT 'VISIBLE', 
	blind_reason VARCHAR(500), 
	blinded_by BIGINT UNSIGNED, 
	blinded_at DATETIME, 
	created_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id), 
	CONSTRAINT ck_reviews_rating CHECK (rating BETWEEN 1 AND 5), 
	CONSTRAINT ck_reviews_blind_reason CHECK (status <> 'BLINDED' OR blind_reason IS NOT NULL), 
	FOREIGN KEY(product_id) REFERENCES products (id) ON DELETE CASCADE, 
	FOREIGN KEY(blinded_by) REFERENCES users (id) ON DELETE SET NULL
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_unicode_ci;

CREATE INDEX ix_reviews_product_status_reviewed ON reviews (product_id, status, reviewed_at);

CREATE TABLE product_monthly_stats (
	product_id BIGINT UNSIGNED NOT NULL, 
	month DATE NOT NULL, 
	buyers INTEGER NOT NULL DEFAULT '0', 
	PRIMARY KEY (product_id, month), 
	FOREIGN KEY(product_id) REFERENCES products (id) ON DELETE CASCADE
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_unicode_ci;

CREATE TABLE review_analysis (
	id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
	review_id BIGINT UNSIGNED NOT NULL, 
	sentiment ENUM('POS','NEG','NEU') NOT NULL, 
	sentiment_score FLOAT, 
	severity TINYINT UNSIGNED NOT NULL DEFAULT '0', 
	issue_type ENUM('PRODUCT','DELIVERY','PACKAGING','ETC'), 
	model_version VARCHAR(50) NOT NULL, 
	analyzed_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id), 
	CONSTRAINT ck_review_analysis_severity CHECK (severity BETWEEN 0 AND 3), 
	UNIQUE (review_id), 
	FOREIGN KEY(review_id) REFERENCES reviews (id) ON DELETE CASCADE
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_unicode_ci;

CREATE INDEX ix_review_analysis_issue_severity ON review_analysis (issue_type, severity);

CREATE TABLE review_keywords (
	review_id BIGINT UNSIGNED NOT NULL, 
	keyword_id BIGINT UNSIGNED NOT NULL, 
	score FLOAT, 
	PRIMARY KEY (review_id, keyword_id), 
	FOREIGN KEY(review_id) REFERENCES reviews (id) ON DELETE CASCADE, 
	FOREIGN KEY(keyword_id) REFERENCES keywords (id) ON DELETE CASCADE
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_unicode_ci;

CREATE INDEX ix_review_keywords_keyword ON review_keywords (keyword_id);

CREATE TABLE review_blind_logs (
	id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
	review_id BIGINT UNSIGNED NOT NULL, 
	actor_id BIGINT UNSIGNED, 
	action ENUM('BLIND','RESTORE') NOT NULL, 
	reason VARCHAR(500), 
	created_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id), 
	FOREIGN KEY(review_id) REFERENCES reviews (id) ON DELETE CASCADE, 
	FOREIGN KEY(actor_id) REFERENCES users (id) ON DELETE SET NULL
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_unicode_ci;

CREATE INDEX ix_review_blind_logs_review_created ON review_blind_logs (review_id, created_at);

CREATE TABLE review_replies (
	id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
	review_id BIGINT UNSIGNED NOT NULL, 
	parent_id BIGINT UNSIGNED, 
	author_id BIGINT UNSIGNED, 
	content TEXT NOT NULL, 
	created_at DATETIME NOT NULL DEFAULT now(), 
	updated_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id), 
	FOREIGN KEY(review_id) REFERENCES reviews (id) ON DELETE CASCADE, 
	FOREIGN KEY(parent_id) REFERENCES review_replies (id) ON DELETE CASCADE, 
	FOREIGN KEY(author_id) REFERENCES users (id) ON DELETE SET NULL
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_unicode_ci;

CREATE INDEX ix_review_replies_review_parent ON review_replies (review_id, parent_id);

CREATE TABLE reply_suggestions (
	id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
	review_id BIGINT UNSIGNED NOT NULL, 
	draft TEXT NOT NULL, 
	llm_model VARCHAR(100) NOT NULL, 
	created_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id), 
	FOREIGN KEY(review_id) REFERENCES reviews (id) ON DELETE CASCADE
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_unicode_ci;

CREATE INDEX ix_reply_suggestions_review_created ON reply_suggestions (review_id, created_at);


-- ── v1.1 추가 (migrations/versions/0002_v1_1_notifications_reply_templates.py) ──

CREATE TABLE notification_settings (
	seller_id BIGINT UNSIGNED NOT NULL, 
	risk_email BOOL NOT NULL DEFAULT '0', 
	updated_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (seller_id), 
	FOREIGN KEY(seller_id) REFERENCES users (id) ON DELETE CASCADE
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE reply_templates (
	id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
	seller_id BIGINT UNSIGNED NOT NULL, 
	sentiment ENUM('POS','NEG','NEU') NOT NULL, 
	content TEXT NOT NULL, 
	updated_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id), 
	CONSTRAINT uq_reply_templates_seller_sentiment UNIQUE (seller_id, sentiment), 
	FOREIGN KEY(seller_id) REFERENCES users (id) ON DELETE CASCADE
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_unicode_ci;


-- ── v1.2 추가 (migrations/versions/0003_v1_2_actions_memos.py) ──

CREATE TABLE product_actions (
	id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
	product_id BIGINT UNSIGNED NOT NULL, 
	action_date DATE NOT NULL, 
	title VARCHAR(200) NOT NULL, 
	issue_type ENUM('PRODUCT','DELIVERY','PACKAGING','ETC'), 
	created_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id), 
	FOREIGN KEY(product_id) REFERENCES products (id) ON DELETE CASCADE
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE INDEX ix_product_actions_product_date ON product_actions (product_id, action_date);

CREATE TABLE review_memos (
	review_id BIGINT UNSIGNED NOT NULL, 
	status ENUM('TODO','IN_PROGRESS','DONE') NOT NULL DEFAULT 'TODO', 
	memo TEXT, 
	updated_by BIGINT UNSIGNED, 
	updated_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (review_id), 
	FOREIGN KEY(review_id) REFERENCES reviews (id) ON DELETE CASCADE, 
	FOREIGN KEY(updated_by) REFERENCES users (id) ON DELETE SET NULL
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_unicode_ci;
