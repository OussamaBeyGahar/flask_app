-- Database Structure and Relations for DmaExportTool

-- 1. Table: page
-- Stores the different endpoints/pages available in the application for access control.
CREATE TABLE page (
    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(100) NOT NULL UNIQUE,
    endpoint VARCHAR(100) NOT NULL UNIQUE
);

-- 2. Table: user
-- Stores user account information and their approval/admin status.
CREATE TABLE user (
    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    username VARCHAR(150) NOT NULL UNIQUE,
    email VARCHAR(150) NOT NULL UNIQUE,
    first_name VARCHAR(150) NOT NULL,
    last_name VARCHAR(150) NOT NULL,
    country VARCHAR(50) NOT NULL,
    password VARCHAR(150) NOT NULL,
    is_admin BOOLEAN,
    is_approved BOOLEAN
);

-- 3. Table: user_pages (Association Table)
-- Manages the many-to-many relationship between users and the pages they are authorized to access.
CREATE TABLE user_pages (
    user_id INTEGER NOT NULL,
    page_id INTEGER NOT NULL,
    PRIMARY KEY (user_id, page_id),
    FOREIGN KEY(user_id) REFERENCES user (id),
    FOREIGN KEY(page_id) REFERENCES page (id)
);
