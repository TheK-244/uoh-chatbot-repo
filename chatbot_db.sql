- Clean chatbot_db database
-- Keeps only the admin account and the required category rows.
-- All chat messages, conversations, requests, items, item_meta, and ai_documents are removed.

CREATE DATABASE IF NOT EXISTS `chatbot_db`
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE `chatbot_db`;

SET SQL_MODE = "NO_AUTO_VALUE_ON_ZERO";
SET time_zone = "+00:00";
SET FOREIGN_KEY_CHECKS = 0;

DROP TABLE IF EXISTS `ai_documents`;
DROP TABLE IF EXISTS `item_meta`;
DROP TABLE IF EXISTS `messages`;
DROP TABLE IF EXISTS `user_requests`;
DROP TABLE IF EXISTS `conversations`;
DROP TABLE IF EXISTS `items`;
DROP TABLE IF EXISTS `users`;
DROP TABLE IF EXISTS `categories`;

SET FOREIGN_KEY_CHECKS = 1;

CREATE TABLE `categories` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `name` varchar(50) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `users` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `name` varchar(120) NOT NULL,
  `email` varchar(190) NOT NULL,
  `password_hash` varchar(255) NULL,
  `is_admin` tinyint(1) NOT NULL DEFAULT 0,
  `is_verified` tinyint(1) NOT NULL DEFAULT 0,
  `verification_code` varchar(6) DEFAULT NULL,
  `oauth_provider` varchar(50) DEFAULT NULL,
  `oauth_id` varchar(255) DEFAULT NULL,
  `created_at` timestamp NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `email` (`email`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `items` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `category_id` int(11) NOT NULL,
  `title` varchar(255) NOT NULL,
  `content` text DEFAULT NULL,
  `created_at` timestamp NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  KEY `fk_items_category` (`category_id`),
  CONSTRAINT `fk_items_category`
    FOREIGN KEY (`category_id`) REFERENCES `categories` (`id`)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `item_meta` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `item_id` int(11) NOT NULL,
  `meta_key` varchar(100) NOT NULL,
  `meta_value` text NOT NULL,
  PRIMARY KEY (`id`),
  KEY `fk_item_meta_item` (`item_id`),
  CONSTRAINT `fk_item_meta_item`
    FOREIGN KEY (`item_id`) REFERENCES `items` (`id`)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `ai_documents` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `item_id` int(11) NOT NULL,
  `content` longtext NOT NULL,
  `embedding` longtext NOT NULL,
  `updated_at` timestamp NOT NULL DEFAULT current_timestamp() ON UPDATE current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `item_id` (`item_id`),
  CONSTRAINT `fk_ai_documents_item`
    FOREIGN KEY (`item_id`) REFERENCES `items` (`id`)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `conversations` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `user_id` int(11) NOT NULL,
  `title` varchar(255) NOT NULL DEFAULT 'New Conversation',
  `needs_clarification` tinyint(1) NOT NULL DEFAULT 0,
  `clarification_count` int(11) NOT NULL DEFAULT 0,
  `created_at` timestamp NOT NULL DEFAULT current_timestamp(),
  `updated_at` timestamp NOT NULL DEFAULT current_timestamp() ON UPDATE current_timestamp(),
  PRIMARY KEY (`id`),
  KEY `idx_conversations_user` (`user_id`),
  CONSTRAINT `fk_conversations_user`
    FOREIGN KEY (`user_id`) REFERENCES `users` (`id`)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `messages` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `conversation_id` int(11) NOT NULL,
  `role` enum('user','assistant') NOT NULL,
  `content` longtext NOT NULL,
  `created_at` timestamp NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  KEY `idx_messages_conversation` (`conversation_id`),
  CONSTRAINT `fk_messages_conversation`
    FOREIGN KEY (`conversation_id`) REFERENCES `conversations` (`id`)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `user_requests` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `user_id` int(11) NOT NULL,
  `question` text NOT NULL,
  `answer` text DEFAULT NULL,
  `status` enum('pending','answered','ignored') NOT NULL DEFAULT 'pending',
  `created_at` timestamp NOT NULL DEFAULT current_timestamp(),
  `answered_at` timestamp NULL DEFAULT NULL,
  `hidden_by_user` tinyint(1) NOT NULL DEFAULT 0,
  `updated_at` timestamp NOT NULL DEFAULT current_timestamp() ON UPDATE current_timestamp(),
  PRIMARY KEY (`id`),
  KEY `user_id` (`user_id`),
  CONSTRAINT `user_requests_ibfk_1`
    FOREIGN KEY (`user_id`) REFERENCES `users` (`id`)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO `categories` (`id`, `name`) VALUES
  (1, 'faculty'),
  (2, 'building'),
  (3, 'faq');

INSERT INTO `users` (`id`, `name`, `email`, `password_hash`, `is_admin`, `is_verified`, `created_at`) VALUES
  (1, 'admin', 'admin@gmail.com', 'scrypt:32768:8:1$31hU60Z24N46aFIN$1e7113a8eba91c0daaccff08014c609cd5dd493aa3512edaf069e3fd9d1b4655678683ae15be896b6aef47c73565c703cc47456f63c085a697862f90b192e9dd', 1, 1, '2026-05-14 10:29:10');

ALTER TABLE `categories` AUTO_INCREMENT = 4;
ALTER TABLE `users` AUTO_INCREMENT = 2;
ALTER TABLE `items` AUTO_INCREMENT = 1;
ALTER TABLE `item_meta` AUTO_INCREMENT = 1;
ALTER TABLE `ai_documents` AUTO_INCREMENT = 1;
ALTER TABLE `conversations` AUTO_INCREMENT = 1;
ALTER TABLE `messages` AUTO_INCREMENT = 1;
ALTER TABLE `user_requests` AUTO_INCREMENT = 1;
