import unittest
from scripts.configure_application_roles import validate_user

class ReviewedIdentityTests(unittest.TestCase):
    def setUp(self):
        self.assignment = {'subject':'reviewed-sub','email':'person@example.test','group':'spip-tester'}
        self.user = {'UserAttributes':[{'Name':'sub','Value':'reviewed-sub'}, {'Name':'email','Value':'PERSON@example.test'}]}

    def test_reviewed_identity_matches_case_insensitive_email(self):
        validate_user(self.user,self.assignment)

    def test_different_subject_is_rejected(self):
        with self.assertRaises(ValueError): validate_user(self.user,{**self.assignment,'subject':'other-sub'})

    def test_different_email_is_rejected(self):
        with self.assertRaises(ValueError): validate_user(self.user,{**self.assignment,'email':'other@example.test'})

    def test_unknown_group_is_rejected(self):
        with self.assertRaises(ValueError): validate_user(self.user,{**self.assignment,'group':'arbitrary-role'})
