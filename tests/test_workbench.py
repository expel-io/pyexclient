import copy
import datetime
import uuid
from unittest.mock import MagicMock
from unittest.mock import Mock
from unittest.mock import patch
from urllib.parse import unquote

import pytest

from pyexclient.workbench import base_flag
from pyexclient.workbench import contains
from pyexclient.workbench import gt
from pyexclient.workbench import include
from pyexclient.workbench import Investigations
from pyexclient.workbench import is_operator
from pyexclient.workbench import isnull
from pyexclient.workbench import limit
from pyexclient.workbench import lt
from pyexclient.workbench import neq
from pyexclient.workbench import notnull
from pyexclient.workbench import relationship_op
from pyexclient.workbench import sort
from pyexclient.workbench import startswith
from pyexclient.workbench import window
from pyexclient.workbench import WorkbenchClient

ORGANIZATION_ID = '11111111-1111-1111-1111-111111111111'


def get_url_from_request_mock(x):
    return unquote(x.request.call_args[0][1])


@pytest.fixture()
def mock_xclient():
    with patch.object(WorkbenchClient, 'request') as mock_method:
        x = WorkbenchClient('', '', '')
        mock_method.return_value = Mock()
        mock_method.return_value.json.return_value = {}

        yield x


def test_user_agent_set(mock_xclient):
    assert mock_xclient.session.headers['User-Agent'] == 'pyexclient'


class TestNotNullOperator:
    def test_false(self, mock_xclient):
        mock_xclient.investigations.search(close_comment=notnull(False))
        result = get_url_from_request_mock(mock_xclient)
        assert result == '/api/v2/investigations?filter[close_comment]=\u2400true&sort=+created_at&sort=+id'

        mock_xclient.investigations.search(relationship_op('comments.comment', notnull(False)))
        result = get_url_from_request_mock(mock_xclient)
        assert result == '/api/v2/investigations?filter[comments][comment]=\u2400true&sort=+created_at&sort=+id'

    def test_true(self, mock_xclient):
        mock_xclient.investigations.search(close_comment=notnull(True))
        result = get_url_from_request_mock(mock_xclient)
        assert result == '/api/v2/investigations?filter[close_comment]=\u2400false&sort=+created_at&sort=+id'

        mock_xclient.investigations.search(relationship_op('comments.comment', notnull(True)))
        result = get_url_from_request_mock(mock_xclient)
        assert result == '/api/v2/investigations?filter[comments][comment]=\u2400false&sort=+created_at&sort=+id'

    def test_except(self, mock_xclient):
        with pytest.raises(ValueError):
            mock_xclient.investigations.search(close_comment=notnull(21123))

        with pytest.raises(ValueError):
            mock_xclient.investigations.search(relationship_op('comments.comment', notnull(21123)))


class TestIsNullOperator:
    def test_false(self, mock_xclient):
        mock_xclient.investigations.search(close_comment=isnull(False))
        result = get_url_from_request_mock(mock_xclient)
        assert result == '/api/v2/investigations?filter[close_comment]=\u2400false&sort=+created_at&sort=+id'

        mock_xclient.investigations.search(relationship_op('comments.comment', isnull(False)))
        result = get_url_from_request_mock(mock_xclient)
        assert result == '/api/v2/investigations?filter[comments][comment]=\u2400false&sort=+created_at&sort=+id'

    def test_true(self, mock_xclient):
        mock_xclient.investigations.search(close_comment=isnull(True))
        result = get_url_from_request_mock(mock_xclient)
        assert result == '/api/v2/investigations?filter[close_comment]=\u2400true&sort=+created_at&sort=+id'

        mock_xclient.investigations.search(relationship_op('comments.comment', isnull(True)))
        result = get_url_from_request_mock(mock_xclient)
        assert result == '/api/v2/investigations?filter[comments][comment]=\u2400true&sort=+created_at&sort=+id'

    def test_except(self, mock_xclient):
        with pytest.raises(ValueError):
            mock_xclient.investigations.search(close_comment=isnull(21123))

        with pytest.raises(ValueError):
            mock_xclient.investigations.search(relationship_op('comments.comment', isnull(21123)))


class TestContainsOperator:
    def test_none(self, mock_xclient):
        mock_xclient.investigations.search(close_comment=contains())
        result = get_url_from_request_mock(mock_xclient)
        assert result == '/api/v2/investigations?sort=+created_at&sort=+id'

        mock_xclient.investigations.search(relationship_op('comments.comment', contains()))
        result = get_url_from_request_mock(mock_xclient)
        assert result == '/api/v2/investigations?sort=+created_at&sort=+id'

    def test_values(self, mock_xclient):
        mock_xclient.investigations.search(close_comment=contains('one', 'two'))
        result = get_url_from_request_mock(mock_xclient)
        assert result == '/api/v2/investigations?filter[close_comment]=:one&filter[close_comment]=:two&sort=+created_at&sort=+id'

        mock_xclient.investigations.search(relationship_op('comments.comment', contains('one', 'two')))
        result = get_url_from_request_mock(mock_xclient)
        assert result == '/api/v2/investigations?filter[comments][comment]=:one&filter[comments][comment]=:two&sort=+created_at&sort=+id'


class TestStartsWithOperator:
    def test_values(self, mock_xclient):
        mock_xclient.investigations.search(close_comment=startswith('one'))
        result = get_url_from_request_mock(mock_xclient)
        assert result == '/api/v2/investigations?filter[close_comment]=^one&sort=+created_at&sort=+id'

        mock_xclient.investigations.search(relationship_op('comments.comment', startswith('one')))
        result = get_url_from_request_mock(mock_xclient)
        assert result == '/api/v2/investigations?filter[comments][comment]=^one&sort=+created_at&sort=+id'


class TestNotEqualsOperator:
    def test_none(self, mock_xclient):
        mock_xclient.investigations.search(close_comment=neq())
        result = get_url_from_request_mock(mock_xclient)
        assert result == '/api/v2/investigations?sort=+created_at&sort=+id'

        mock_xclient.investigations.search(relationship_op('comments.comment', neq()))
        result = get_url_from_request_mock(mock_xclient)
        assert result == '/api/v2/investigations?sort=+created_at&sort=+id'

    def test_values(self, mock_xclient):
        mock_xclient.investigations.search(close_comment=neq('one', 'two'))
        result = get_url_from_request_mock(mock_xclient)
        assert result == '/api/v2/investigations?filter[close_comment]=!one&filter[close_comment]=!two&sort=+created_at&sort=+id'

        mock_xclient.investigations.search(relationship_op('comments.comment', neq('one', 'two')))
        result = get_url_from_request_mock(mock_xclient)
        assert result == '/api/v2/investigations?filter[comments][comment]=!one&filter[comments][comment]=!two&sort=+created_at&sort=+id'


class TestGreaterThanOperator:
    def test_datetime(self, mock_xclient):
        dt = datetime.datetime(2020, 1, 1)

        mock_xclient.investigations.search(close_comment=gt(dt))
        result = get_url_from_request_mock(mock_xclient)
        assert result == '/api/v2/investigations?filter[close_comment]=>2020-01-01T00:00:00&sort=+created_at&sort=+id'

        mock_xclient.investigations.search(relationship_op('comments.comment', gt(dt)))
        result = get_url_from_request_mock(mock_xclient)
        assert result == '/api/v2/investigations?filter[comments][comment]=>2020-01-01T00:00:00&sort=+created_at&sort=+id'

    def test_other(self, mock_xclient):
        mock_xclient.investigations.search(close_comment=gt(245))
        result = get_url_from_request_mock(mock_xclient)
        assert result == '/api/v2/investigations?filter[close_comment]=>245&sort=+created_at&sort=+id'

        mock_xclient.investigations.search(relationship_op('comments.comment', gt(245)))
        result = get_url_from_request_mock(mock_xclient)
        assert result == '/api/v2/investigations?filter[comments][comment]=>245&sort=+created_at&sort=+id'


class TestLessThanOperator:
    def test_datetime(self, mock_xclient):
        dt = datetime.datetime(2020, 1, 1)

        mock_xclient.investigations.search(close_comment=lt(dt))
        result = get_url_from_request_mock(mock_xclient)
        assert result == '/api/v2/investigations?filter[close_comment]=<2020-01-01T00:00:00&sort=+created_at&sort=+id'

        mock_xclient.investigations.search(relationship_op('comments.comment', lt(dt)))
        result = get_url_from_request_mock(mock_xclient)
        assert result == '/api/v2/investigations?filter[comments][comment]=<2020-01-01T00:00:00&sort=+created_at&sort=+id'

    def test_other(self, mock_xclient):
        mock_xclient.investigations.search(close_comment=lt(245))
        result = get_url_from_request_mock(mock_xclient)
        assert result == '/api/v2/investigations?filter[close_comment]=<245&sort=+created_at&sort=+id'

        mock_xclient.investigations.search(relationship_op('comments.comment', lt(245)))
        result = get_url_from_request_mock(mock_xclient)
        assert result == '/api/v2/investigations?filter[comments][comment]=<245&sort=+created_at&sort=+id'


class TestWindowOperator:
    def test_datetimes(self, mock_xclient):
        dt_1 = datetime.datetime(2020, 1, 1)
        dt_2 = datetime.datetime(2020, 5, 1)

        mock_xclient.investigations.search(close_comment=window(dt_1, dt_2))
        result = get_url_from_request_mock(mock_xclient)
        assert result == '/api/v2/investigations?filter[close_comment]=>2020-01-01T00:00:00&filter[close_comment]=<2020-05-01T00:00:00&sort=+created_at&sort=+id'

        mock_xclient.investigations.search(relationship_op('comments.comment', window(dt_1, dt_2)))
        result = get_url_from_request_mock(mock_xclient)
        assert result == '/api/v2/investigations?filter[comments][comment]=>2020-01-01T00:00:00&filter[comments][comment]=<2020-05-01T00:00:00&sort=+created_at&sort=+id'

    def test_other(self, mock_xclient):
        mock_xclient.investigations.search(close_comment=window(100, 500))
        result = get_url_from_request_mock(mock_xclient)
        assert result == '/api/v2/investigations?filter[close_comment]=>100&filter[close_comment]=<500&sort=+created_at&sort=+id'

        mock_xclient.investigations.search(relationship_op('comments.comment', window(100, 500)))
        result = get_url_from_request_mock(mock_xclient)
        assert result == '/api/v2/investigations?filter[comments][comment]=>100&filter[comments][comment]=<500&sort=+created_at&sort=+id'


class TestFlagOperator:
    def test_value(self, mock_xclient):
        mock_xclient.investigations.search(close_comment=base_flag('test'))
        result = get_url_from_request_mock(mock_xclient)
        assert result == '/api/v2/investigations?flag[close_comment]=test&sort=+created_at&sort=+id'


class TestrelationshipOperator:
    def test_init_except(self, mock_xclient):
        too_long = 'comment.comment.comment'
        with pytest.raises(ValueError):
            relationship_op(too_long, '')

    def test_no_rels(self, mock_xclient):
        rel = relationship_op('comment.comment', '')
        with pytest.raises(ValueError) as e:
            rel.create_query_filters()

        assert str(e.value) == 'Relationship operator has no class relationships defined'

    def test_relationship_op_does_not_exist(self, mock_xclient):
        rel = relationship_op('something.not_existing', '')
        rel.rels = ['one', 'two']
        with pytest.raises(ValueError) as e:
            rel.create_query_filters()

        assert 'not a defined relationship' in str(e.value)

    def test_create_operator(self, mock_xclient):
        rel = relationship_op('comments.comment', window(123, 456))
        rel.rels = ['comments']

        result = rel.create_query_filters()
        assert result == [('filter[comments][comment]', '>123'),
                          ('filter[comments][comment]', '<456')]

    def test_create_value(self, mock_xclient):
        rel = relationship_op('comments.comment', 'some value')
        rel.rels = ['comments']

        result = rel.create_query_filters()
        assert result == [('filter[comments][comment]', 'some value')]


class TestLimitOperator:
    def test_value(self, mock_xclient):
        mock_xclient.investigations.search(limit(5))
        result = get_url_from_request_mock(mock_xclient)
        assert result == '/api/v2/investigations?page[limit]=5&sort=+created_at&sort=+id'


class TestIncludeOperator:
    def test_value(self, mock_xclient):
        mock_xclient.investigations.search(include('organization,created_by,updated_by'))
        result = get_url_from_request_mock(mock_xclient)
        assert result == '/api/v2/investigations?include=organization,created_by,updated_by&sort=+created_at&sort=+id'


class TestSortOperator:
    def test_default(self, mock_xclient):
        mock_xclient.investigations.search()
        result = get_url_from_request_mock(mock_xclient)
        assert result == '/api/v2/investigations?sort=+created_at&sort=+id'

        mock_xclient.investigations.search(sort('created_at'))
        result = get_url_from_request_mock(mock_xclient)
        assert result == '/api/v2/investigations?sort=+created_at'

    def test_asc(self, mock_xclient):
        mock_xclient.investigations.search(sort('created_at', '+'))
        result = get_url_from_request_mock(mock_xclient)
        assert result == '/api/v2/investigations?sort=+created_at'

        mock_xclient.investigations.search(sort('created_at', 'asc'))
        result = get_url_from_request_mock(mock_xclient)
        assert result == '/api/v2/investigations?sort=+created_at'

    def test_desc(self, mock_xclient):
        mock_xclient.investigations.search(sort('created_at', '-'))
        result = get_url_from_request_mock(mock_xclient)
        assert result == '/api/v2/investigations?sort=-created_at'

        mock_xclient.investigations.search(sort('created_at', 'desc'))
        result = get_url_from_request_mock(mock_xclient)
        assert result == '/api/v2/investigations?sort=-created_at'

    def test_multiple(self, mock_xclient):
        mock_xclient.investigations.search(sort('created_at', '-'), sort('id', '+'), sort('closed_at', '-'))
        result = get_url_from_request_mock(mock_xclient)
        assert result == '/api/v2/investigations?sort=-created_at&sort=+id&sort=-closed_at'

    def test_value_error(self, mock_xclient):
        with pytest.raises(ValueError):
            sort('field', 12341434)


class TestIsOperator:
    def test_true(self):
        op = notnull(True)
        assert is_operator(op) is True

    def test_false(self):
        not_op = datetime.datetime(2020, 1, 1)
        assert is_operator(not_op) is False


class TestBaseResourceObject:
    def test_make_url(self, mock_xclient):
        result = mock_xclient.investigations.make_url(
            'investigations')
        assert result == '/api/v2/investigations'

        result = mock_xclient.investigations.make_url(
            'investigations', value='56f00b9b-8fdf-4f7d-aca0-de431f7f50e6')
        assert result == '/api/v2/investigations/56f00b9b-8fdf-4f7d-aca0-de431f7f50e6'

        result = mock_xclient.investigations.make_url(
            'investigations', value='56f00b9b-8fdf-4f7d-aca0-de431f7f50e6',
            relation='investigative_actions')
        assert result == '/api/v2/investigations/56f00b9b-8fdf-4f7d-aca0-de431f7f50e6/investigative_actions'

        result = mock_xclient.investigations.make_url(
            'investigations', value='56f00b9b-8fdf-4f7d-aca0-de431f7f50e6',
            relation='investigative_actions', relationship=True)
        assert result == '/api/v2/investigations/56f00b9b-8fdf-4f7d-aca0-de431f7f50e6/relationships/investigative_actions'

    def test_fetch_page(self, mock_xclient, raw_investigation_dict):
        mock_xclient.request.return_value.json.return_value = {
            'data': [raw_investigation_dict for _ in range(3)],
            'included': [raw_investigation_dict for _ in range(3)]
        }
        result = mock_xclient.investigations._fetch_page('test_url')
        assert len(result['data']) == 3
        assert len(result['included']) == 3

        for inv in result['data']:
            assert isinstance(inv, Investigations)
        for inv in result['included']:
            assert isinstance(inv, Investigations)

        # test not list -> list conversion
        mock_xclient.request.return_value.json.return_value = {'data': raw_investigation_dict}
        result = mock_xclient.investigations._fetch_page('test_url')
        assert len(result['data']) == 1
        assert isinstance(result['data'], list)
        assert isinstance(result['data'][0], Investigations)
        assert len(result['included']) == 0

    def test_filter_by(self, mock_xclient, raw_investigation_dict):
        mock_xclient.request.return_value.json.side_effect = [
            {'data': [raw_investigation_dict for _ in range(3)], 'links': {'next': 'aaa'}},
            {'data': [raw_investigation_dict for _ in range(3)], 'links': {'next': 'bbb'}},
            {'data': [raw_investigation_dict for _ in range(3)]},
        ]
        invs = []
        for inv in mock_xclient.investigations.filter_by():
            invs.append(inv)
            assert isinstance(inv, Investigations)
            assert inv._id == 'e12da56a-1111-1111-9b73-111ba6852193'
        assert len(invs) == 9

    def test_search_complex_args(self, mock_xclient):
        args = [
            relationship_op('investigation.created_at', gt(datetime.datetime(2020, 1, 1))),
            relationship_op('investigation.created_at', lt(datetime.datetime(2020, 5, 1))),
            relationship_op('investigation.organization_id', ORGANIZATION_ID)
        ]
        kwargs = {
            'action_types': 'MANUAL',

        }
        mock_xclient.investigative_actions.search(*args, **kwargs)
        result = get_url_from_request_mock(mock_xclient)
        assert result == '/api/v2/investigative_actions?filter[investigation][created_at]=>2020-01-01T00:00:00&filter[investigation][created_at]=<2020-05-01T00:00:00&filter[investigation][organization][id]=11111111-1111-1111-1111-111111111111&filter[action_types]=MANUAL&sort=+created_at&sort=+id'

    def test_search_more_complex_args(self, mock_xclient):
        args = [
            relationship_op('investigation.created_at', gt(datetime.datetime(2020, 1, 1))),
            relationship_op('investigation.created_at', lt(datetime.datetime(2020, 5, 1))),
            relationship_op('investigation.organization_id', ORGANIZATION_ID),
            sort('created_at')
        ]
        kwargs = {
            'action_types': 'MANUAL',
            'some_count': gt(25),
            'some_other_count': window(1, 5)
        }
        mock_xclient.investigative_actions.search(*args, **kwargs)
        result = get_url_from_request_mock(mock_xclient)
        assert result == '/api/v2/investigative_actions?filter[investigation][created_at]=>2020-01-01T00:00:00&filter[investigation][created_at]=<2020-05-01T00:00:00&filter[investigation][organization][id]=11111111-1111-1111-1111-111111111111&sort=+created_at&filter[action_types]=MANUAL&filter[some_count]=>25&filter[some_other_count]=>1&filter[some_other_count]=<5'

    def test_search_sort(self, mock_xclient):
        mock_xclient.investigative_actions.search(sort('some_timestamp', '-'))
        result = get_url_from_request_mock(mock_xclient)
        assert result == '/api/v2/investigative_actions?sort=-some_timestamp'

    def test_search_default_sort(self, mock_xclient):
        mock_xclient.investigative_actions.search()
        result = get_url_from_request_mock(mock_xclient)
        assert result == '/api/v2/investigative_actions?sort=+created_at&sort=+id'

    def test_search_arg_except(self, mock_xclient):
        with pytest.raises(ValueError):
            mock_xclient.investigative_actions.search('something')

    def test_count(self, mock_xclient, raw_investigation_dict):
        mock_xclient.request.return_value.json.return_value = {'meta': {'page': {'total': 57}}}
        assert mock_xclient.investigations.count() == 57

        mock_xclient.request.return_value.json.side_effect = [
            {'data': [raw_investigation_dict for _ in range(3)], 'meta': {'page': {'total': 100}}}
        ]
        result = mock_xclient.investigations.search().count()
        assert result == 100

    def test_one_or_none(self, mock_xclient, raw_investigation_dict):
        mock_xclient.request.return_value.json.return_value = {}
        assert mock_xclient.investigations.one_or_none() is None

        mock_xclient.request.return_value.json.return_value = {'data': raw_investigation_dict}
        result = mock_xclient.investigations.one_or_none()
        assert isinstance(result, Investigations)

    def test_get_exceptions(self, mock_xclient):
        with pytest.raises(ValueError) as e:
            mock_xclient.investigations.get(**{'not': 'an id'})
        assert str(e.value) == 'Expected `id` argument in get call'

        with pytest.raises(ValueError) as e:
            mock_xclient.investigations.get(**{'id': 'args', 'many more': 'args'})
        assert str(e.value) == 'Expected a single argument `id` in get call'

    def test_get(self, mock_xclient, raw_investigation_dict):
        mock_xclient.request.return_value.json.return_value = {'data': raw_investigation_dict}
        inv = mock_xclient.investigations.get(id='e12da56a-1111-1111-9b73-111ba6852193')
        assert isinstance(inv, Investigations)
        assert inv._create is False

    def test_iter_no_next(self, mock_xclient, raw_investigation_dict):
        mock_xclient.request.return_value.json.side_effect = [
            {'data': [raw_investigation_dict for _ in range(3)]}
        ]
        invs = []
        for inv in mock_xclient.investigations:
            invs.append(inv)
            assert isinstance(inv, Investigations)
            assert inv._id == 'e12da56a-1111-1111-9b73-111ba6852193'
        assert len(invs) == 3

    def test_iter_no_content(self, mock_xclient, raw_investigation_dict):
        mock_xclient.request.return_value.json.side_effect = [
            {'data': [raw_investigation_dict for _ in range(3)], 'links': {'next': 'aaa'}},
            {'data': [raw_investigation_dict for _ in range(3)], 'links': {'next': 'bbb'}},
            {'data': [raw_investigation_dict for _ in range(3)]},
        ]
        invs = []
        for inv in mock_xclient.investigations:
            invs.append(inv)
            assert isinstance(inv, Investigations)
            assert inv._id == 'e12da56a-1111-1111-9b73-111ba6852193'
        assert len(invs) == 9

    def test_iter_content(self, mock_xclient, raw_investigation_dict):
        mock_xclient.request.return_value.json.side_effect = [
            {'data': [raw_investigation_dict for _ in range(3)], 'links': {'next': 'aaa'}},
            {'data': [raw_investigation_dict for _ in range(3)], 'links': {'next': 'bbb'}},
            {'data': [raw_investigation_dict for _ in range(3)]},
        ]
        invs = []
        for inv in mock_xclient.investigations.filter_by():
            invs.append(inv)
            assert isinstance(inv, Investigations)
            assert inv._id == 'e12da56a-1111-1111-9b73-111ba6852193'
        assert len(invs) == 9

        mock_xclient.request.return_value.json.side_effect = [
            {'data': [raw_investigation_dict for _ in range(3)],
             'included': [raw_investigation_dict for _ in range(3)], 'links': {'next': 'aaa'}},
            {'data': [raw_investigation_dict for _ in range(3)],
             'included': [raw_investigation_dict for _ in range(3)], 'links': {'next': 'bbb'}},
            {'data': [raw_investigation_dict for _ in range(3)],
             'included': [raw_investigation_dict for _ in range(3)]},
        ]
        invs = []
        for inv in mock_xclient.investigations.filter_by():
            invs.append(inv)
            assert isinstance(inv, Investigations)
            assert inv._id == 'e12da56a-1111-1111-9b73-111ba6852193'
        assert len(invs) == 18

    def test_create(self, mock_xclient, raw_investigation_dict):
        inv = mock_xclient.investigations.create(**raw_investigation_dict['attributes'])
        assert isinstance(inv, Investigations)
        assert inv._create is True


class TestResourceInstance:
    def test_save(self, raw_investigation_dict):
        mock_conn = Mock()
        ret_dict = copy.deepcopy(raw_investigation_dict)
        ret_dict['id'] = '111'
        mock_conn.request.return_value.json.return_value = {'data': ret_dict}

        inv = Investigations.create(mock_conn, **raw_investigation_dict['attributes'])
        assert inv.id is None
        assert inv.short_link == 'TEST-489'
        assert inv._create is True
        inv.save()
        assert inv.id == '111'
        inv.short_link = 'SOME VAL'
        assert inv._create is False
        inv.save()

    def test_create(self, raw_investigation_dict):
        mock_conn = Mock()
        ret_dict = copy.deepcopy(raw_investigation_dict)
        ret_dict['id'] = '111'
        mock_conn.request.return_value.json.return_value = {'data': ret_dict}

        inv = Investigations.create(mock_conn, **raw_investigation_dict['attributes'])
        assert inv.id is None
        assert inv.short_link == 'TEST-489'
        assert inv._create is True
        inv.save()
        assert inv.id == '111'

    def test_str(self, raw_investigation_dict):
        # make sure str sets the _id attribute properly
        mock_conn = Mock()
        ret_dict = copy.deepcopy(raw_investigation_dict)
        ret_dict['id'] = '111'
        mock_conn.request.return_value.json.return_value = {'data': ret_dict}

        inv = Investigations.create(mock_conn, **raw_investigation_dict['attributes'])
        inv.save()
        result = str(inv)
        assert "'id': '111'" in result

    def test_delete(self, raw_investigation_dict):
        mock_conn = Mock()
        ret_dict = copy.deepcopy(raw_investigation_dict)
        ret_dict['id'] = '111'
        mock_conn.request.return_value.json.return_value = {'data': ret_dict}

        inv = Investigations.create(mock_conn, **raw_investigation_dict['attributes'])
        inv.save()
        inv.delete()
        assert inv._deleted is True


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
