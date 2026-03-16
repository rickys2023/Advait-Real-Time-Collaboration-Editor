"""
Unit Tests for Real-Time Collaboration Editor
Demonstrates testing expertise for top tech companies
"""

import unittest
import json
import time
from unittest.mock import Mock, patch, MagicMock
import sys
sys.path.insert(0, '.')

from app import (
    app, 
    DocumentDatabase, 
    OperationalTransform, 
    SessionManager,
    socketio
)

# ============================================================================
# TEST CONFIGURATION
# ============================================================================

class TestConfig:
    TESTING = True
    DATABASE = ':memory:'

class CollaborationEditorTestCase(unittest.TestCase):
    """Base test case for collaboration editor"""
    
    def setUp(self):
        """Set up test client and database"""
        app.config['TESTING'] = True
        app.config['SECRET_KEY'] = 'test-secret-key'
        self.app = app
        self.client = self.app.test_client()
        
        # Initialize test database
        DocumentDatabase.init_db()
    
    def tearDown(self):
        """Clean up after tests"""
        SessionManager.active_sessions.clear()
        SessionManager.document_sessions.clear()

# ============================================================================
# DATABASE TESTS
# ============================================================================

class TestDocumentDatabase(CollaborationEditorTestCase):
    """Test database operations"""
    
    def test_create_document(self):
        """Test document creation"""
        doc_id = DocumentDatabase.create_document('Test Doc', 'user123')
        
        self.assertIsNotNone(doc_id)
        self.assertTrue(len(doc_id) > 0)
    
    def test_get_document(self):
        """Test retrieving document"""
        created_id = DocumentDatabase.create_document('Test Doc', 'user123')
        doc = DocumentDatabase.get_document(created_id)
        
        self.assertIsNotNone(doc)
        self.assertEqual(doc['title'], 'Test Doc')
        self.assertEqual(doc['owner_id'], 'user123')
        self.assertEqual(doc['content'], '')
        self.assertEqual(doc['version'], 0)
    
    def test_get_nonexistent_document(self):
        """Test retrieving non-existent document"""
        doc = DocumentDatabase.get_document('nonexistent-id')
        
        self.assertIsNone(doc)
    
    def test_update_document(self):
        """Test document update"""
        doc_id = DocumentDatabase.create_document('Test Doc', 'user123')
        new_content = 'Updated content'
        
        DocumentDatabase.update_document(doc_id, new_content, 1)
        doc = DocumentDatabase.get_document(doc_id)
        
        self.assertEqual(doc['content'], new_content)
        self.assertEqual(doc['version'], 1)
    
    def test_log_change(self):
        """Test change logging"""
        doc_id = DocumentDatabase.create_document('Test Doc', 'user123')
        operation = json.dumps({'type': 'insert', 'pos': 0, 'text': 'Hello'})
        
        # Should not raise exception
        DocumentDatabase.log_change(doc_id, 'user123', operation, 1)
    
    def test_get_changes(self):
        """Test retrieving change history"""
        doc_id = DocumentDatabase.create_document('Test Doc', 'user123')
        
        operation1 = json.dumps({'type': 'insert', 'pos': 0, 'text': 'Hello'})
        operation2 = json.dumps({'type': 'insert', 'pos': 5, 'text': ' World'})
        
        DocumentDatabase.log_change(doc_id, 'user123', operation1, 1)
        DocumentDatabase.log_change(doc_id, 'user123', operation2, 2)
        
        changes = DocumentDatabase.get_changes(doc_id, 0)
        
        self.assertEqual(len(changes), 2)
        self.assertEqual(changes[0]['version'], 1)
        self.assertEqual(changes[1]['version'], 2)

# ============================================================================
# OPERATIONAL TRANSFORMATION TESTS
# ============================================================================

class TestOperationalTransform(CollaborationEditorTestCase):
    """Test operational transformation engine"""
    
    def test_transform_insert_insert(self):
        """Test transforming two concurrent inserts"""
        op1 = {'type': 'insert', 'pos': 0, 'text': 'A'}
        op2 = {'type': 'insert', 'pos': 1, 'text': 'B'}
        
        op1_prime, op2_prime = OperationalTransform.transform(op1, op2)
        
        # If op1 is at position 0, op2 should shift right
        self.assertEqual(op1_prime['pos'], 0)
        self.assertEqual(op2_prime['pos'], 2)  # Shifted by length of op1's text
    
    def test_transform_insert_delete(self):
        """Test transforming insert and delete operations"""
        op_insert = {'type': 'insert', 'pos': 5, 'text': 'X'}
        op_delete = {'type': 'delete', 'pos': 3, 'length': 2}
        
        op_i, op_d = OperationalTransform.transform(op_insert, op_delete)
        
        # Insert at 5 with delete at 3-5 should result in insert at 3
        self.assertEqual(op_i['type'], 'insert')
        self.assertEqual(op_d['type'], 'delete')
    
    def test_apply_insert_operation(self):
        """Test applying insert operation to content"""
        content = "Hello World"
        operation = {'type': 'insert', 'pos': 6, 'text': 'Beautiful '}
        
        result = OperationalTransform.apply_operation(content, operation)
        
        self.assertEqual(result, "Hello Beautiful World")
    
    def test_apply_delete_operation(self):
        """Test applying delete operation to content"""
        content = "Hello World"
        operation = {'type': 'delete', 'pos': 5, 'length': 6}
        
        result = OperationalTransform.apply_operation(content, operation)
        
        self.assertEqual(result, "Hello")
    
    def test_apply_insert_at_beginning(self):
        """Test insert at beginning of content"""
        content = "World"
        operation = {'type': 'insert', 'pos': 0, 'text': 'Hello '}
        
        result = OperationalTransform.apply_operation(content, operation)
        
        self.assertEqual(result, "Hello World")
    
    def test_apply_delete_at_end(self):
        """Test delete at end of content"""
        content = "HelloWorld"
        operation = {'type': 'delete', 'pos': 5, 'length': 5}
        
        result = OperationalTransform.apply_operation(content, operation)
        
        self.assertEqual(result, "Hello")

# ============================================================================
# SESSION MANAGEMENT TESTS
# ============================================================================

class TestSessionManager(CollaborationEditorTestCase):
    """Test session management"""
    
    def test_create_session(self):
        """Test creating a new session"""
        session_id = SessionManager.create_session('user123', 'TestUser')
        
        self.assertIsNotNone(session_id)
        self.assertIn(session_id, SessionManager.active_sessions)
        self.assertEqual(SessionManager.active_sessions[session_id]['user_id'], 'user123')
        self.assertEqual(SessionManager.active_sessions[session_id]['username'], 'TestUser')
    
    def test_add_to_document(self):
        """Test adding session to document"""
        session_id = SessionManager.create_session('user123', 'TestUser')
        doc_id = 'doc123'
        
        SessionManager.add_to_document(session_id, doc_id)
        
        self.assertIn(doc_id, SessionManager.document_sessions)
        self.assertIn(session_id, SessionManager.document_sessions[doc_id]['participants'])
    
    def test_remove_from_document(self):
        """Test removing session from document"""
        session_id = SessionManager.create_session('user123', 'TestUser')
        doc_id = 'doc123'
        
        SessionManager.add_to_document(session_id, doc_id)
        SessionManager.remove_from_document(session_id, doc_id)
        
        self.assertNotIn(session_id, SessionManager.document_sessions[doc_id]['participants'])
    
    def test_multiple_users_in_document(self):
        """Test multiple users in same document"""
        session_id1 = SessionManager.create_session('user1', 'User1')
        session_id2 = SessionManager.create_session('user2', 'User2')
        doc_id = 'doc123'
        
        SessionManager.add_to_document(session_id1, doc_id)
        SessionManager.add_to_document(session_id2, doc_id)
        
        participants = SessionManager.document_sessions[doc_id]['participants']
        self.assertEqual(len(participants), 2)
        self.assertIn(session_id1, participants)
        self.assertIn(session_id2, participants)

# ============================================================================
# API ENDPOINT TESTS
# ============================================================================

class TestAPIEndpoints(CollaborationEditorTestCase):
    """Test HTTP API endpoints"""
    
    def test_create_document_endpoint(self):
        """Test POST /api/documents"""
        response = self.client.post(
            '/api/documents',
            json={'title': 'Test Document'},
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertIn('doc_id', data)
        self.assertIn('user_id', data)
    
    def test_get_document_endpoint(self):
        """Test GET /api/documents/<doc_id>"""
        # Create document first
        create_response = self.client.post(
            '/api/documents',
            json={'title': 'Test Document'},
            content_type='application/json'
        )
        doc_id = json.loads(create_response.data)['doc_id']
        
        # Get document
        get_response = self.client.get(f'/api/documents/{doc_id}')
        
        self.assertEqual(get_response.status_code, 200)
        data = json.loads(get_response.data)
        self.assertEqual(data['title'], 'Test Document')
        self.assertEqual(data['version'], 0)
    
    def test_get_nonexistent_document(self):
        """Test GET /api/documents/<doc_id> with non-existent ID"""
        response = self.client.get('/api/documents/nonexistent-id')
        
        self.assertEqual(response.status_code, 404)
    
    def test_get_document_history(self):
        """Test GET /api/documents/<doc_id>/history"""
        # Create document
        create_response = self.client.post(
            '/api/documents',
            json={'title': 'Test Document'},
            content_type='application/json'
        )
        doc_id = json.loads(create_response.data)['doc_id']
        
        # Get history
        response = self.client.get(f'/api/documents/{doc_id}/history?from_version=0')
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertIsInstance(data, list)

# ============================================================================
# CONCURRENCY TESTS
# ============================================================================

class TestConcurrency(CollaborationEditorTestCase):
    """Test concurrent operations"""
    
    def test_concurrent_inserts_same_position(self):
        """Test two concurrent inserts at same position"""
        op1 = {'type': 'insert', 'pos': 0, 'text': 'A'}
        op2 = {'type': 'insert', 'pos': 0, 'text': 'B'}
        
        op1_prime, op2_prime = OperationalTransform.transform(op1, op2)
        
        # Should result in valid transformed operations
        self.assertIsNotNone(op1_prime)
        self.assertIsNotNone(op2_prime)
        self.assertEqual(op1_prime['type'], 'insert')
        self.assertEqual(op2_prime['type'], 'insert')
    
    def test_concurrent_delete_operations(self):
        """Test concurrent delete operations"""
        op1 = {'type': 'delete', 'pos': 0, 'length': 2}
        op2 = {'type': 'delete', 'pos': 3, 'length': 2}
        
        op1_prime, op2_prime = OperationalTransform.transform(op1, op2)
        
        # Should result in valid transformed operations
        self.assertEqual(op1_prime['type'], 'delete')
        self.assertEqual(op2_prime['type'], 'delete')

# ============================================================================
# INTEGRATION TESTS
# ============================================================================

class TestIntegration(CollaborationEditorTestCase):
    """Integration tests for full workflows"""
    
    def test_complete_document_workflow(self):
        """Test complete document creation and modification workflow"""
        # 1. Create document
        doc_id = DocumentDatabase.create_document('Integration Test', 'user1')
        self.assertIsNotNone(doc_id)
        
        # 2. Get document
        doc = DocumentDatabase.get_document(doc_id)
        self.assertEqual(doc['content'], '')
        
        # 3. Apply operation
        operation = {'type': 'insert', 'pos': 0, 'text': 'Hello World'}
        new_content = OperationalTransform.apply_operation(doc['content'], operation)
        
        # 4. Update document
        DocumentDatabase.update_document(doc_id, new_content, 1)
        
        # 5. Verify update
        updated_doc = DocumentDatabase.get_document(doc_id)
        self.assertEqual(updated_doc['content'], 'Hello World')
        self.assertEqual(updated_doc['version'], 1)
    
    def test_multi_user_editing_sequence(self):
        """Test sequence of edits from multiple users"""
        doc_id = DocumentDatabase.create_document('Multi-user Test', 'user1')
        content = ""
        version = 0
        
        # User 1: Insert "Hello"
        op1 = {'type': 'insert', 'pos': 0, 'text': 'Hello'}
        content = OperationalTransform.apply_operation(content, op1)
        version += 1
        DocumentDatabase.update_document(doc_id, content, version)
        
        # User 2: Insert " World" at end
        op2 = {'type': 'insert', 'pos': len(content), 'text': ' World'}
        content = OperationalTransform.apply_operation(content, op2)
        version += 1
        DocumentDatabase.update_document(doc_id, content, version)
        
        # Verify final state
        final_doc = DocumentDatabase.get_document(doc_id)
        self.assertEqual(final_doc['content'], 'Hello World')
        self.assertEqual(final_doc['version'], 2)

# ============================================================================
# PERFORMANCE TESTS
# ============================================================================

class TestPerformance(CollaborationEditorTestCase):
    """Performance benchmarks"""
    
    def test_large_document_operations(self):
        """Test performance with large document"""
        doc_id = DocumentDatabase.create_document('Large Doc', 'user1')
        
        # Simulate adding 1000 characters
        start_time = time.time()
        content = ""
        for i in range(1000):
            op = {'type': 'insert', 'pos': len(content), 'text': 'A'}
            content = OperationalTransform.apply_operation(content, op)
        
        duration = time.time() - start_time
        
        # Should complete in reasonable time (< 1 second)
        self.assertLess(duration, 1.0)
        self.assertEqual(len(content), 1000)
    
    def test_many_concurrent_operations(self):
        """Test performance with many concurrent operations"""
        start_time = time.time()
        
        operations = [
            {'type': 'insert', 'pos': i, 'text': f'Op{i}'}
            for i in range(100)
        ]
        
        # Transform each operation against others
        for i, op in enumerate(operations):
            for j in range(i):
                OperationalTransform.transform(op, operations[j])
        
        duration = time.time() - start_time
        
        # Should complete reasonably fast
        self.assertLess(duration, 2.0)

# ============================================================================
# TEST RUNNER
# ============================================================================

if __name__ == '__main__':
    # Run tests with verbosity
    unittest.main(verbosity=2)
