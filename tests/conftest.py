import pytest


@pytest.fixture
def raw_investigation_dict():
    return {
        'type': 'investigations',
        'attributes': {
            'status_updated_at': '2020-09-18T15:37:32.983Z',
            'review_requested_at': None,
            'title': 'Peter: new investigation 1',
            'critical_comment': None,
            'last_published_value': None,
            'lead_description': None,
            'is_surge': False,
            'updated_at': '2020-09-18T15:37:32.983Z',
            'last_published_at': None,
            'properties': None,
            'analyst_severity': None,
            'is_downgrade': False,
            'is_incident': False,
            'attack_timing': None,
            'attack_lifecycle': None,
            'created_at': '2020-09-18T15:37:32.983Z',
            'is_incident_status_updated_at': '2020-09-18T15:37:32.983Z',
            'short_link': 'TEST-489',
            'decision': None,
            'deleted_at': None,
            'has_hunting_status': False,
            'close_comment': None,
            'attack_vector': None,
            'detection_type': None,
            'threat_type': None,
            'source_reason': None
        },
        'id': 'e12da56a-1111-1111-9b73-111ba6852193',
        'links': {
            'self': 'http://workbench/api/v2/investigations/e12da56a-421b-484c-9b73-313ba6852193'
        },
        'relationships': {
            'comments': {
                'links': {
                    'self': 'http://workbench/api/v2/investigations/e12da56a-421b-484c-9b73-313ba6852193/relationships/comments',
                    'related': 'http://workbench/api/v2/investigations/e12da56a-421b-484c-9b73-313ba6852193/comments'
                },
                'meta': {
                    'relation': 'primary', 'readOnly': False
                }
            },
            'investigation_histories': {
                'links': {
                    'self': 'http://workbench/api/v2/investigations/e12da56a-421b-484c-9b73-313ba6852193/relationships/investigation_histories',
                    'related': 'http://workbench/api/v2/investigations/e12da56a-421b-484c-9b73-313ba6852193/investigation_histories'
                },
                'meta': {
                    'relation': 'primary', 'readOnly': False
                }
            }
        }
    }
