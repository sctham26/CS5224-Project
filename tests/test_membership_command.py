import unittest
from scripts.add_tenant_member import resolve_subject

class MembershipIdentityTests(unittest.TestCase):
    def test_only_one_enabled_exact_email_can_be_assigned(self):
        email = 'member@example.com'
        subject = '79eaa52c-8031-7013-b836-2bfe3e75b049'
        user = {'Enabled': True, 'Attributes': [dict(Name='email', Value=email), dict(Name='sub', Value=subject)]}
        self.assertEqual(resolve_subject([user], email), subject)
        for users in ([], [user, user], [dict(user, Enabled=False)]):
            with self.assertRaises(ValueError):
                resolve_subject(users, email)
        with self.assertRaises(ValueError):
            resolve_subject([user], 'another@example.com')
