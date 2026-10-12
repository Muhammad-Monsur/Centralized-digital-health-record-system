
-- CDHRS - MySQL reference schema

CREATE DATABASE IF NOT EXISTS cdhrs CHARACTER SET utf8mb4;
USE cdhrs;

-- 1. core user & hospital cluster 
CREATE TABLE hospitals (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(150) NOT NULL,
    address VARCHAR(255) DEFAULT '',
    phone VARCHAR(30) DEFAULT '',
    status VARCHAR(20) DEFAULT 'Active'
);


--  real departments 
CREATE TABLE departments (
    id INT AUTO_INCREMENT PRIMARY KEY,
    hospital_id INT NOT NULL REFERENCES hospitals(id),
    name VARCHAR(100) NOT NULL,
    nurse_count INT DEFAULT 0,
    staff_count INT DEFAULT 0
);

CREATE TABLE users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    email VARCHAR(150) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(20) NOT NULL,          -- patient | doctor | hospital_admin | system_admin
    full_name VARCHAR(150) NOT NULL,
    phone VARCHAR(30) DEFAULT '',
    gender VARCHAR(20) DEFAULT '',
    status VARCHAR(20) DEFAULT 'Active', -- Active | Blocked
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 2. role based access control (RBAC) 
CREATE TABLE roles (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(50) UNIQUE NOT NULL,
    description VARCHAR(255) DEFAULT ''
);

CREATE TABLE permissions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    description VARCHAR(255) DEFAULT ''
);

CREATE TABLE user_roles (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users(id),
    role_id INT NOT NULL REFERENCES roles(id)
);

CREATE TABLE role_permissions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    role_id INT NOT NULL REFERENCES roles(id),
    permission_id INT NOT NULL REFERENCES permissions(id)
);

--3. patient & medical information cluster 
CREATE TABLE patients (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT UNIQUE NOT NULL REFERENCES users(id),
    upi VARCHAR(20) UNIQUE NOT NULL,     -- Unique Patient ID, e.g. P-000178
    date_of_birth VARCHAR(20) DEFAULT '',
    blood_group VARCHAR(10) DEFAULT '',
    address VARCHAR(255) DEFAULT '',
    profile_visibility VARCHAR(10) DEFAULT 'Public'
);

CREATE TABLE doctors (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT UNIQUE NOT NULL REFERENCES users(id),
    hospital_id INT NOT NULL REFERENCES hospitals(id),
    department_id INT NULL REFERENCES departments(id),   
    specialization VARCHAR(100) DEFAULT '',
    verification_status VARCHAR(20) DEFAULT 'Active'
);

CREATE TABLE hospital_admins (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT UNIQUE NOT NULL REFERENCES users(id),
    hospital_id INT NOT NULL REFERENCES hospitals(id)
);

CREATE TABLE system_admins (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT UNIQUE NOT NULL REFERENCES users(id)
);

CREATE TABLE medical_information (
    id INT AUTO_INCREMENT PRIMARY KEY,
    patient_id INT NOT NULL REFERENCES patients(id),
    doctor_id INT REFERENCES doctors(id),
    hospital_id INT REFERENCES hospitals(id),
    information_type VARCHAR(30) NOT NULL,  -- record | prescription | lab_report
    title VARCHAR(150) NOT NULL,
    details TEXT,
    file_path VARCHAR(255) DEFAULT '',
    visibility VARCHAR(10) DEFAULT 'Public',
    information_date DATETIME DEFAULT CURRENT_TIMESTAMP,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

--  real admissions 
CREATE TABLE admissions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    patient_id INT NOT NULL REFERENCES patients(id),
    hospital_id INT NOT NULL REFERENCES hospitals(id),
    ward VARCHAR(100) DEFAULT 'General Ward',
    admitted_on DATETIME DEFAULT CURRENT_TIMESTAMP,
    discharged_on DATETIME NULL,
    status VARCHAR(20) DEFAULT 'Admitted'   -- Admitted | Discharged
);

--  4. privacy & consent cluster 
CREATE TABLE access_requests (
    id INT AUTO_INCREMENT PRIMARY KEY,
    patient_id INT NOT NULL REFERENCES patients(id),
    doctor_id INT NOT NULL REFERENCES doctors(id),
    purpose VARCHAR(255) DEFAULT '',
    status VARCHAR(20) DEFAULT 'Pending',  -- Pending | Approved | Rejected | Expired
    requested_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE consents (
    id INT AUTO_INCREMENT PRIMARY KEY,
    request_id INT NOT NULL REFERENCES access_requests(id),
    patient_id INT NOT NULL REFERENCES patients(id),
    doctor_id INT NOT NULL REFERENCES doctors(id),
    status VARCHAR(20) DEFAULT 'Pending',  -- Pending | Approved | Rejected | Revoked
    granted_at DATETIME NULL,
    expires_at DATETIME NULL,
    revoked_at DATETIME NULL
);

CREATE TABLE otp_verifications (
    id INT AUTO_INCREMENT PRIMARY KEY,
    consent_id INT NOT NULL REFERENCES consents(id),
    otp_hash VARCHAR(255) NOT NULL,
    generated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME NOT NULL,
    verified_at DATETIME NULL
);

-- one-time codes for the "Forgot Password?" flow
CREATE TABLE password_reset_tokens (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users(id),
    code_hash VARCHAR(255) NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME NOT NULL,
    used_at DATETIME NULL
);

--  5. emergency access cluster 
CREATE TABLE emergency_access (
    id INT AUTO_INCREMENT PRIMARY KEY,
    patient_id INT NOT NULL REFERENCES patients(id),
    doctor_id INT NOT NULL REFERENCES doctors(id),
    hospital_id INT REFERENCES hospitals(id),
    reason TEXT NOT NULL,
    accessed_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 6. access history & audit cluster 
CREATE TABLE access_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users(id),
    patient_id INT NOT NULL REFERENCES patients(id),
    access_type VARCHAR(50) NOT NULL,
    accessed_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE audit_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT REFERENCES users(id),
    action VARCHAR(150) NOT NULL,
    entity VARCHAR(50) DEFAULT '',
    entity_id INT NULL,
    details VARCHAR(255) DEFAULT '',
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);
