"""
Real-Time Collaborative Document Editor
Production-grade implementation with WebSocket support, operational transformation,
and comprehensive document management for enterprise use.
"""

from flask import Flask, render_template, request, jsonify, session 
from flask_socketio import SocketIO, emit, join_room, leave_room, rooms
from flask_cors import CORS
import sqlite3
import json
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import hashlib
import os
import logging

# ============================================================================
# CONFIGURATION & SETUP
# ============================================================================

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-key-change-in-production')
app.config['SESSION_TYPE'] = 'filesystem'
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================================
# DATABASE LAYER
# ============================================================================

class DocumentDatabase:
    """Handles all persistent storage operations."""
    
    DB_PATH = 'collaboration.db'
    
    @staticmethod
    def init_db():
        """Initialize database schema."""
        conn = sqlite3.connect(DocumentDatabase.DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                content TEXT DEFAULT '',
                version INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                owner_id TEXT NOT NULL,
                is_public BOOLEAN DEFAULT 0
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS collaborators (
                document_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                permission_level TEXT DEFAULT 'view',
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (document_id, user_id),
                FOREIGN KEY (document_id) REFERENCES documents(id),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS changes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                operation TEXT NOT NULL,
                version INTEGER NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (document_id) REFERENCES documents(id),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        
        conn.commit()
        conn.close()
    
    @staticmethod
    def create_document(title: str, owner_id: str) -> str:
        """Create a new document."""
        doc_id = str(uuid.uuid4())
        conn = sqlite3.connect(DocumentDatabase.DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute(
            'INSERT INTO documents (id, title, owner_id, content) VALUES (?, ?, ?, ?)',
            (doc_id, title, owner_id, '')
        )
        conn.commit()
        conn.close()
        return doc_id
    
    @staticmethod
    def get_document(doc_id: str) -> Optional[Dict]:
        """Retrieve document by ID."""
        conn = sqlite3.connect(DocumentDatabase.DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM documents WHERE id = ?', (doc_id,))
        doc = cursor.fetchone()
        conn.close()
        
        return dict(doc) if doc else None
    
    @staticmethod
    def update_document(doc_id: str, content: str, version: int):
        """Update document content and version."""
        conn = sqlite3.connect(DocumentDatabase.DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute(
            'UPDATE documents SET content = ?, version = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
            (content, version, doc_id)
        )
        conn.commit()
        conn.close()
    
    @staticmethod
    def log_change(doc_id: str, user_id: str, operation: str, version: int):
        """Log document change for audit trail."""
        conn = sqlite3.connect(DocumentDatabase.DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute(
            'INSERT INTO changes (document_id, user_id, operation, version) VALUES (?, ?, ?, ?)',
            (doc_id, user_id, operation, version)
        )
        conn.commit()
        conn.close()
    
    @staticmethod
    def get_changes(doc_id: str, from_version: int) -> List[Dict]:
        """Retrieve all changes after a specific version."""
        conn = sqlite3.connect(DocumentDatabase.DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute(
            'SELECT * FROM changes WHERE document_id = ? AND version > ? ORDER BY version',
            (doc_id, from_version)
        )
        changes = cursor.fetchall()
        conn.close()
        
        return [dict(c) for c in changes]

# ============================================================================
# OPERATIONAL TRANSFORMATION ENGINE
# ============================================================================

class OperationalTransform:
    """
    Implements Operational Transformation for conflict-free collaborative editing.
    This handles simultaneous edits from multiple users.
    """
    
    @staticmethod
    def transform(op1: Dict, op2: Dict) -> Tuple[Dict, Dict]:
        """
        Transform two concurrent operations to maintain consistency.
        Returns transformed (op1', op2') that can be applied in either order.
        """
        
        # Simple position-based transformation
        # Insert/Delete operations relative to position in text
        
        if op1['type'] == 'insert' and op2['type'] == 'insert':
            if op1['pos'] < op2['pos']:
                op2['pos'] += len(op1['text'])
            elif op1['pos'] > op2['pos']:
                op1['pos'] += len(op2['text'])
            return op1, op2
        
        elif op1['type'] == 'delete' and op2['type'] == 'delete':
            if op1['pos'] < op2['pos']:
                op2['pos'] -= op1['length']
            elif op1['pos'] > op2['pos']:
                op1['pos'] -= op2['length']
            return op1, op2
        
        elif op1['type'] == 'insert' and op2['type'] == 'delete':
            if op1['pos'] <= op2['pos']:
                op2['pos'] += len(op1['text'])
            else:
                op1['pos'] -= op2['length']
            return op1, op2
        
        elif op1['type'] == 'delete' and op2['type'] == 'insert':
            if op2['pos'] <= op1['pos']:
                op1['pos'] += len(op2['text'])
            else:
                op2['pos'] -= op1['length']
            return op1, op2
        
        return op1, op2
    
    @staticmethod
    def apply_operation(content: str, operation: Dict) -> str:
        """Apply an operation to content."""
        if operation['type'] == 'insert':
            pos = operation['pos']
            text = operation['text']
            return content[:pos] + text + content[pos:]
        
        elif operation['type'] == 'delete':
            pos = operation['pos']
            length = operation['length']
            return content[:pos] + content[pos + length:]
        
        return content

# ============================================================================
# SESSION & USER MANAGEMENT
# ============================================================================

class SessionManager:
    """Manages user sessions and document sessions."""
    
    active_sessions: Dict[str, Dict] = {}
    document_sessions: Dict[str, Dict] = {}
    
    @staticmethod
    def create_session(user_id: str, username: str) -> str:
        """Create a new user session."""
        session_id = str(uuid.uuid4())
        SessionManager.active_sessions[session_id] = {
            'user_id': user_id,
            'username': username,
            'created_at': datetime.now(),
            'active_documents': []
        }
        return session_id
    
    @staticmethod
    def add_to_document(session_id: str, doc_id: str):
        """Add session to document workspace."""
        if session_id in SessionManager.active_sessions:
            SessionManager.active_sessions[session_id]['active_documents'].append(doc_id)
        
        if doc_id not in SessionManager.document_sessions:
            SessionManager.document_sessions[doc_id] = {
                'version': 0,
                'participants': [],
                'pending_ops': []
            }
        
        if session_id not in SessionManager.document_sessions[doc_id]['participants']:
            SessionManager.document_sessions[doc_id]['participants'].append(session_id)
    
    @staticmethod
    def remove_from_document(session_id: str, doc_id: str):
        """Remove session from document."""
        if doc_id in SessionManager.document_sessions:
            if session_id in SessionManager.document_sessions[doc_id]['participants']:
                SessionManager.document_sessions[doc_id]['participants'].remove(session_id)

# ============================================================================
# FLASK ROUTES
# ============================================================================

@app.route('/')
def index():
    """Serve main application."""
    return render_template('index.html')

@app.route('/api/documents', methods=['POST'])
def create_document():
    """Create a new document."""
    data = request.json
    user_id = session.get('user_id', str(uuid.uuid4()))
    
    doc_id = DocumentDatabase.create_document(
        title=data.get('title', 'Untitled Document'),
        owner_id=user_id
    )
    
    session['user_id'] = user_id
    return jsonify({'doc_id': doc_id, 'user_id': user_id})

@app.route('/api/documents/<doc_id>', methods=['GET'])
def get_document(doc_id):
    """Retrieve document content."""
    doc = DocumentDatabase.get_document(doc_id)
    
    if not doc:
        return jsonify({'error': 'Document not found'}), 404
    
    return jsonify({
        'id': doc['id'],
        'title': doc['title'],
        'content': doc['content'],
        'version': doc['version'],
        'owner_id': doc['owner_id'],
        'updated_at': doc['updated_at']
    })

@app.route('/api/documents/<doc_id>/history', methods=['GET'])
def get_document_history(doc_id):
    """Retrieve change history."""
    from_version = request.args.get('from_version', 0, type=int)
    changes = DocumentDatabase.get_changes(doc_id, from_version)
    return jsonify(changes)

# ============================================================================
# WEBSOCKET EVENTS
# ============================================================================

@socketio.on('connect')
def handle_connect():
    """Handle new WebSocket connection."""
    user_id = str(uuid.uuid4())
    username = request.args.get('username', f'User_{user_id[:8]}')
    
    session_id = SessionManager.create_session(user_id, username)
    
    logger.info(f'Client connected: {username} (session: {session_id})')
    emit('connection_response', {
        'session_id': session_id,
        'user_id': user_id,
        'username': username,
        'status': 'connected'
    })

@socketio.on('join_document')
def handle_join_document(data):
    """Handle user joining a document."""
    doc_id = data['doc_id']
    session_id = data.get('session_id')
    
    if not session_id or session_id not in SessionManager.active_sessions:
        emit('error', {'message': 'Invalid session'})
        return
    
    # Join room for broadcasting
    join_room(doc_id)
    SessionManager.add_to_document(session_id, doc_id)
    
    # Retrieve document
    doc = DocumentDatabase.get_document(doc_id)
    if not doc:
        emit('error', {'message': 'Document not found'})
        return
    
    session_info = SessionManager.active_sessions[session_id]
    
    # Notify others
    emit('user_joined', {
        'username': session_info['username'],
        'user_count': len(SessionManager.document_sessions[doc_id]['participants'])
    }, room=doc_id)
    
    # Send document state to joining user
    emit('document_loaded', {
        'content': doc['content'],
        'version': doc['version'],
        'title': doc['title'],
        'users_online': len(SessionManager.document_sessions[doc_id]['participants'])
    })
    
    logger.info(f"{session_info['username']} joined document {doc_id}")

@socketio.on('edit')
def handle_edit(data):
    """Handle edit operation from client."""
    doc_id = data['doc_id']
    session_id = data.get('session_id')
    operation = data['operation']
    client_version = data.get('version', 0)
    
    if doc_id not in SessionManager.document_sessions:
        emit('error', {'message': 'Document session not found'})
        return
    
    doc = DocumentDatabase.get_document(doc_id)
    session_info = SessionManager.active_sessions.get(session_id, {})
    
    # Operational Transformation
    server_version = doc['version']
    
    if client_version != server_version:
        # Client version mismatch - transform operation
        pending_ops = SessionManager.document_sessions[doc_id]['pending_ops']
        for pending_op in pending_ops[client_version:]:
            operation, _ = OperationalTransform.transform(operation, pending_op)
    
    # Apply operation
    new_content = OperationalTransform.apply_operation(doc['content'], operation)
    new_version = server_version + 1
    
    # Update database
    DocumentDatabase.update_document(doc_id, new_content, new_version)
    DocumentDatabase.log_change(
        doc_id,
        session_info.get('user_id', 'unknown'),
        json.dumps(operation),
        new_version
    )
    
    # Store operation for future transformations
    SessionManager.document_sessions[doc_id]['pending_ops'].append(operation)
    SessionManager.document_sessions[doc_id]['version'] = new_version
    
    # Broadcast to all participants
    emit('content_update', {
        'content': new_content,
        'version': new_version,
        'operation': operation,
        'user': session_info.get('username', 'Unknown'),
        'timestamp': datetime.now().isoformat()
    }, room=doc_id)
    
    logger.info(f"Document {doc_id} updated to version {new_version}")

@socketio.on('cursor_move')
def handle_cursor_move(data):
    """Broadcast cursor position for awareness."""
    doc_id = data['doc_id']
    session_id = data.get('session_id')
    position = data['position']
    
    session_info = SessionManager.active_sessions.get(session_id, {})
    
    emit('cursor_updated', {
        'user': session_info.get('username', 'Unknown'),
        'position': position,
        'session_id': session_id
    }, room=doc_id, skip_sid=request.sid)

@socketio.on('leave_document')
def handle_leave_document(data):
    """Handle user leaving document."""
    doc_id = data['doc_id']
    session_id = data.get('session_id')
    
    if session_id and session_id in SessionManager.active_sessions:
        session_info = SessionManager.active_sessions[session_id]
        SessionManager.remove_from_document(session_id, doc_id)
        
        leave_room(doc_id)
        
        emit('user_left', {
            'username': session_info['username'],
            'user_count': len(SessionManager.document_sessions.get(doc_id, {}).get('participants', []))
        }, room=doc_id)
        
        logger.info(f"{session_info['username']} left document {doc_id}")

@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection."""
    logger.info('Client disconnected')

# ============================================================================
# INITIALIZATION
# ============================================================================

if __name__ == '__main__':
    DocumentDatabase.init_db()
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)
