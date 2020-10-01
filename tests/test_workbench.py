import datetime
import sys
import uuid
from unittest.mock import MagicMock
from unittest.mock import Mock
from unittest.mock import patch
from urllib.parse import parse_qs
from urllib.parse import unquote
from urllib.parse import urlparse

import pytest

from pyexclient.workbench import BaseResourceObject
from pyexclient.workbench import contains
from pyexclient.workbench import flag
from pyexclient.workbench import gt
from pyexclient.workbench import Investigations
from pyexclient.workbench import isnull
from pyexclient.workbench import lt
from pyexclient.workbench import neq
from pyexclient.workbench import notnull
from pyexclient.workbench import relationship
from pyexclient.workbench import window
from pyexclient.workbench import WorkbenchClient
from pyexclient.workbench import WorkbenchCoreClient

ORGANIZATION_ID = '11111111-1111-1111-1111-111111111111'


def get_url_from_request_mock(x):
    return unquote(x.request.call_args[0][1])


def test_search_operator_null():
    '''
    Test whether we generate the correct request when using isnull and notnull
    '''
    with patch.object(WorkbenchClient, 'request') as mock_method:
        x = WorkbenchClient('', '', '')
        mock_method.return_value = Mock()
        mock_method.return_value.json.return_value = {}

        x.investigations.search(close_comment=notnull())
        assert get_url_from_request_mock(
            x) == '/api/v2/investigations?filter[close_comment]=\u2400false&sort=created_at&sort=id'

        x.investigations.search(close_comment=isnull())
        assert get_url_from_request_mock(
            x) == '/api/v2/investigations?filter[close_comment]=\u2400true&sort=created_at&sort=id'

        x.investigations.search(relationship('comments.comment', isnull()))
        assert get_url_from_request_mock(
            x) == '/api/v2/investigations?filter[comments][comment]=\u2400true&sort=created_at&sort=id'

        x.investigations.search(relationship('comments.comment', notnull()))
        assert get_url_from_request_mock(
            x) == '/api/v2/investigations?filter[comments][comment]=\u2400false&sort=created_at&sort=id'


def test_search_operator_contains():
    '''
    Test whether we build the correct request when using contains
    '''
    with patch.object(WorkbenchClient, 'request') as mock_method:
        x = WorkbenchClient('', '', '')
        mock_method.return_value = Mock()
        mock_method.return_value.json.return_value = {}

        x.investigations.search(close_comment=contains('some'))
        assert get_url_from_request_mock(
            x) == '/api/v2/investigations?filter[close_comment]=:some&sort=created_at&sort=id'

        x.investigations.search(relationship('assigned_to_actor.display_name', contains('Expel')))
        assert get_url_from_request_mock(
            x) == '/api/v2/investigations?filter[assigned_to_actor][display_name]=:Expel&sort=created_at&sort=id'


def test_search_operator_neq():
    '''
    Test whether we get the correct request when using neq
    '''
    with patch.object(WorkbenchClient, 'request') as mock_method:
        x = WorkbenchClient('', '', '')
        mock_method.return_value = Mock()
        mock_method.return_value.json.return_value = {}

        x.investigations.search(close_comment=neq('some'))
        assert get_url_from_request_mock(
            x) == '/api/v2/investigations?filter[close_comment]=!some&sort=created_at&sort=id'


def test_search_operator_window_gt_lt():
    '''
    Test various uses of gt, lt and window operator
    '''
    start_date = '2020-01-01T00:00:00'
    start_dt = datetime.datetime(year=2020, day=1, month=1)

    end_date = '2019-01-01T00:00:00'
    end_dt = datetime.datetime(year=2019, day=1, month=1)

    with patch.object(WorkbenchClient, 'request') as mock_method:
        x = WorkbenchClient('', '', '')
        mock_method.return_value = Mock()
        mock_method.return_value.json.return_value = {}

        # Get investigations created after datetime
        x.investigations.search(created_at=gt(start_dt))
        assert get_url_from_request_mock(
            x) == '/api/v2/investigations?filter[created_at]=>2020-01-01T00:00:00&sort=created_at&sort=id'

        # Get investigations created after date isoformat string
        x.investigations.search(created_at=gt(start_date))
        assert get_url_from_request_mock(
            x) == '/api/v2/investigations?filter[created_at]=>2020-01-01T00:00:00&sort=created_at&sort=id'

        # Get investigations created before datetime
        x.investigations.search(created_at=lt(end_dt))
        assert get_url_from_request_mock(
            x) == '/api/v2/investigations?filter[created_at]=<2019-01-01T00:00:00&sort=created_at&sort=id'

        # Get investigations created before date isoformat
        x.investigations.search(created_at=lt(end_date))
        assert get_url_from_request_mock(
            x) == '/api/v2/investigations?filter[created_at]=<2019-01-01T00:00:00&sort=created_at&sort=id'

        x.investigations.search(created_at=gt(end_dt))
        assert get_url_from_request_mock(
            x) == '/api/v2/investigations?filter[created_at]=>2019-01-01T00:00:00&sort=created_at&sort=id'

        # Get investigations created within the window
        x.investigations.search(window('created_at', start_dt, end_date))
        assert get_url_from_request_mock(
            x) == '/api/v2/investigations?filter[created_at]=>2020-01-01T00:00:00&filter[created_at]=<2019-01-01T00:00:00&sort=created_at&sort=id'

        # Complex filter .. get investigative actions where investigation organization relationship is equal to CUSTOMER_GUID, and investigation was created before start dt and after end dt and wehre the action type for the investigative actoin is mannual
        x.investigative_actions.search(relationship('investigation.organization_id', ORGANIZATION_ID), relationship(
            'investigation.created_at', gt(start_dt)), relationship('investigation.created_at', lt(end_dt)), action_type='MANUAL')
        assert get_url_from_request_mock(
            x) == '/api/v2/investigative_actions?filter[investigation][organization][id]=11111111-1111-1111-1111-111111111111&filter[investigation][created_at]=>2020-01-01T00:00:00&filter[investigation][created_at]=<2019-01-01T00:00:00&filter[action_type]=MANUAL&sort=created_at&sort=id'


@pytest.mark.parametrize("created_at_gt, created_at_lt", [
    ('2020-09-01T01:01:01Z', None),
    (None, '2020-09-01T01:01:01Z'),
    ('2020-09-01T01:01:01Z', '2020-09-02T01:01:01Z')
])
def test_filter_by_range(created_at_gt, created_at_lt):
    '''
    Test the filter by method with ranges
    '''
    with patch.object(WorkbenchClient, 'request') as mock_method1:
        x = WorkbenchClient('', '', '')
        mock_method1.return_value = Mock()
        mock_method1.return_value.json.return_value = {}

        x.investigations.filter_by(created_at_gt=created_at_gt, created_at_lt=created_at_lt)
        queries = urlparse(unquote(x.request.call_args[0][1])).query.split('&')

        if created_at_gt is not None:
            assert 'filter[created_at]=>%s' % created_at_gt in queries

        if created_at_lt is not None:
            assert 'filter[created_at]=<%s' % created_at_lt in queries


@pytest.mark.parametrize("answer,exc_msg,prompt_on_delete", [
    ('n', 'User does not want to execute delete API', True),
    ('b', 'User did not confirm delete!', True),
    ('y', None, True),
    ('n', None, False),
])
@patch('pyexclient.workbench.logger', Mock())
def test_delete_prompt_answer(answer, exc_msg, prompt_on_delete):
    '''
    Test that we prompt on delete, we raise if we dont get corret prompt on delete, and we don't raise when user expected delete
    or opts out of prompting.
    '''

    with patch.object(WorkbenchClient, 'make_session') as mock_method1:
        with patch.object(WorkbenchClient, '_get_user_input') as mock_method2:
            # mock out user input method to return "n"
            mock_method2.return_value = answer

            # Create our WorkbenchClient with make_session mocked out
            x = WorkbenchClient('', '', '')
            # Need to institiate the session variable
            x.session = MagicMock()

            guid = str(uuid.uuid4())
            data = {'attributes': {'title': 'foo'}, 'id': guid}
            inv = Investigations(data, x)
            if exc_msg:
                with pytest.raises(Exception) as e:
                    inv.delete(prompt_on_delete=prompt_on_delete)
                assert str(e.value) == exc_msg, "The message in the expected raised exception did not match"
            else:
                # If we hit here we expect to issue the delete command from the client..
                inv.delete(prompt_on_delete=prompt_on_delete)
                # Assert we issue deleted on the latest route
                assert x.session.request.call_args[1]['url'] == '/api/v2/investigations/%s' % guid
                # Assert we used the right method :)
                assert x.session.request.call_args[1]['method'] == 'delete'
