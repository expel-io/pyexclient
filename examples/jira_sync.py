'''
Script: Jira Sync
Version: 1.0

Sync Expel activities that require customer action to a Jira project. This includes:
- Investigations assigned to the customer
- Investigative actions assigned to the customer
- Remediation actions assigned to the customer
- Comments added to an investigation we're syncing

The script does not sync ALL possible state changes.

This script is provided AS IS - we cannot guarantee it will work on every version of Jira.
It's been tested against Jira Cloud.

We require an API token as described here:
https://confluence.atlassian.com/cloud/api-tokens-938839638.html

Environment Variables:
    JIRA_SERVER = URL for your Jira server
    JIRA_USERNAME = Your Jira User name
    JIRA_API_KEY = Your Jira API key
    WORKBENCH_API_KEY = Your Workbench API key

Requirements:
    jira
    python-dateutil

Usage:
    python jira_sync.py -p PROJECTKEY

'''
import os
import time
import argparse
import sys
import getpass
import logging
logging.basicConfig(level=logging.DEBUG)

from datetime import datetime
from datetime import timedelta
from pyexclient import WorkbenchClient
from pyexclient.workbench import gt
from pyexclient.workbench import contains

try:
    from dateutil import parser as dt_parser
    from jira import JIRA
except ImportError:
    raise ImportError('Missing required package. Run "pip install -r requirements.txt"')


def auth_workbench():
    '''
    Prompt user for authentication info
    '''
    if os.environ.get('WORKBENCH_API_KEY'):
        return WorkbenchClient('https://workbench.expel.io', apikey=os.environ['WORKBENCH_API_KEY'])
    print('''Warning! No api key found in WORKBENCH_API_KEY environment variable.
Prompting for user auth...
Note, your session will expire! Use an API key for long running scripts.''')
    username = input("Enter Username: ")
    password = getpass.getpass("Enter Password: ")
    code = input("2FA Code: ")
    return WorkbenchClient('https://workbench.expel.io', username=username, password=password, mfa_code=code)

def auth_jira():
    '''
    Authenticate to Jira server
    '''
    j_server = os.environ.get('JIRA_SERVER')
    j_user = os.environ.get('JIRA_USERNAME')
    j_key = os.environ.get('JIRA_API_KEY')
    if not (j_server and j_user and j_key):
        raise Exception("Missing required Jira environment variables JIRA_SERVER, JIRA_USERNAME, JIRA_API_KEY")
    return JIRA(
      basic_auth=(j_user, j_key),
      options={
        'server': j_server
      }
    )

class JiraSyncer(object):
    '''
    This class syncs data between Jira and Workbench
    '''
    def __init__(self, workbench_client, jira_client, project, start_at=None):
        self.workbench = workbench_client
        self.jira = jira_client
        self.poll_since = start_at
        self.project = project

    def sync(self):
        '''
        Do all syncing activities between Jira & Workbench
        '''
        self.sync_workbench()
        self.sync_jira()
        self.poll_since = datetime.now() - timedelta(minutes=5)
        logging.info("Updated last poll time to {}".format(self.poll_since))

    def sync_workbench(self):
        '''
        Get new activities from workbench and sync them to Jira
        '''
        logging.info("Syncing investigations from Workbench")
        self.sync_investigations()
        logging.info("Syncing investigative actions from Workbench")
        self.sync_investigative_actions()
        logging.info("Syncing remediation actions from Workbench")
        self.sync_remediation_actions()
        logging.info("Syncing comments from Workbench")
        self.sync_wb_comments()

    def sync_jira(self):
        '''
        TODO: This method is not implemented yet..
        - Get updates from Jira and push them back to Workbench
        '''
        pass

    def sync_investigations(self):
        '''
        Retrieve investigations created since last poll and ensure they
        have tickets created for them.

        Note: We are only polling for investigations assigned to the customer.
        '''
        for inv in self.workbench.investigations.search(updated_at=gt(self.poll_since.isoformat())):
            # Don't sync investigations assigned to Expel
            if inv.assigned_to_actor.is_expel == True:
                continue
            logging.info("Syncing investigation ID: {} updated at: {} title: {}".format(inv.short_link, inv.updated_at, inv.title))
            if inv.decision is None:
                self.create_jira_ticket(inv)
            else:
                self.close_jira_ticket(inv)

    def get_ticket_for_investigation(self, investigation):
        '''
        Given an Expel investigation, find the associated Jira ticket

        Jira ticket references are stored in the investigation properties
        '''
        if investigation.properties:
            return investigation.properties.get('jira-ticket')
        return None

    def _make_inv_description(self, investigation):
        '''
        Make an investigation description for JIRA
        '''
        md = "*Investigation Details*\n"
        md += "https://workbench.expel.io/investigations/{}\n".format(investigation.short_link)
        md += "- Created At: {}\n".format(investigation.created_at)
        md += "- Is Incident: {}\n".format(investigation.is_incident)
        md += "- Severity: {}\n".format(investigation.analyst_severity)
        md += "- Detection Type: {}\n".format(investigation.detection_type)
        md += "- Threat Type: {}\n".format(investigation.threat_type)
        md += "- Source Reason: {}\n".format(investigation.threat_type)
        if investigation.open_comment:
            md += "Open Comment:\n{{noformat}}\n{}\n{{noformat}}\n".format(investigation.open_comment)
        if investigation.lead_expel_alert:
            alert = investigation.lead_expel_alert
            md += "\n*Lead Alert Details*\n"
            md += "- Created At: {}\n".format(alert.created_at)
            md += "- Severity: {}\n".format(alert.expel_severity)
            md += "- Alert Name: {}\n".format(alert.expel_name)
            md += "- Alert Message: {}\n".format(alert.expel_message)
            if alert.evidence:
                md += "\n*Evidence*\n"
                md += "| Type | Evidence |\n"
                for ev in alert.evidence:
                    md += "|{}|{}|\n".format(ev.evidence_type,ev.evidence)
        return md

    def create_jira_ticket(self, investigation):
        '''
        Create a Jira ticket from an Expel investigation
        '''
        existing = self.get_ticket_for_investigation(investigation)
        if existing:
            logging.info("Found existing Jira ticket for investigation, skipping create. Inv ID: {} Jira ID: {}".format(investigation.id, existing))
            return existing
        issue = self.jira.create_issue({
            'project': self.project,
            'summary': '[{short_link}] {title}'.format(short_link=investigation.short_link, title=investigation.title),
            'description': self._make_inv_description(investigation),
            'issuetype': {'name':'Task'},
            })
        # Save jira issue key on investiation properties and add comment
        prop = investigation.properties or {}
        prop['jira-ticket'] = issue.key
        investigation.properties = prop
        c = self.workbench.comments.create(comment="Created JIRA ticket {} to track this investigation.".format(issue.key))
        c.relationship.investigation = investigation.id
        c.save()
        investigation.save()
        logging.info("Created Jira ticket for investigation ID: {} Ticket ID: {}".format(investigation.id, issue.key))
        return issue.key

    def close_jira_ticket(self, investigation):
        '''
        Create a Jira ticket from an Expel investigation
        '''
        issue_key = self.get_ticket_for_investigation(investigation)
        if not issue_key:
            logging.info("Did not find ticket for investigation ID {}, skipping close".format(investigation.id))
            return
        # Transition the issue to done
        issue = self.jira.issues(issue_key)
        close_msg = "Investigation closed as `{dec}` with comment '{cmt}'".format(dec=investigation.decision, cmd=investigation.close_comment)
        self.jira.add_comment(issue.key, close_msg)
        self.jira.transition_issue(issue, transition='Done')
        logging.info("Closed jira ticket for investigation ID: {} ticket ID: {}".format(investigation_id, issue.key))
        return

    def _make_inv_action_message(self, action):
        '''
        Make a Jira ticket message from an investigative action
        '''
        md = "**Reason**\n"
        md += action.reason
        md += "\n**Instructions**\n"
        md += action.instructions
        md += "\n"
        return md

    def sync_investigative_actions(self):
        '''
        Retrieve investigative actions created since last poll and ensure they
        have sub tasks created for them
        '''
        for act in self.workbench.investigative_actions.search(updated_at=gt(self.poll_since.isoformat())):
            # Don't sync actions assigned to Expel
            if act.assigned_to_actor is None or act.assigned_to_actor.is_expel == True:
                continue
            logging.info("Syncing investigative action ID: {} updated at: {} title: {}".format(act.id, act.updated_at, act.title))
            ticket_id = self.create_jira_ticket(act.investigation)
            if act.status == 'READY_FOR_ANALYSIS':
                logging.info("Creating task from investigative action ID: {}".format(act.id))
                self.create_jira_subtask(act.investigation, act.id, ticket_id, act.title, self._make_inv_action_message(act))
            else :
                logging.info("Closing task from investigative action ID: {}".format(act.id))
                self.close_jira_subtask(act.investigation, act.id, act.results)

    def create_jira_subtask(self, investigation, action_id, ticket_id, title, message):
        '''
        Create a Jira sub task associated with ticket_id
        '''
        existing = self.get_jira_subtask(investigation, action_id)
        if existing:
            logging.info("Ticket already has matching sub task, skipping create for ticket ID: {} action ID: {}".format(ticket_id, action_id))
            return existing
        logging.info("Creating new sub task for ticket ID: {} action ID: {} inv ID: {}".format(ticket_id, action_id, investigation.id))
        subtask = self.jira.create_issue({
            'project' : { 'key': self.project },
            'summary' : title,
            'description' : message,
            'issuetype' : { 'name' : 'Subtask' },
            'parent' : { 'key' : ticket_id},
            })
        # store the jira subtasks on investigation properties
        prop = investigation.properties or {}
        task_refs = prop.get('jira-subtasks',{})
        task_refs[action_id] = subtask.key
        task_refs[subtask.key] = action_id
        prop['jira-subtasks'] = task_refs
        investigation.properties = prop
        investigation.save()
        logging.info("Created subtask ID: {} parent ID: {} action ID: {}".format(subtask.key, ticket_id, action_id))
        return subtask.key

    def get_jira_subtask(self, investigation, action_id):
        '''
        Retrieve the Subtask key for an action
        '''
        prop = investigation.properties or {}
        return prop.get('jira-subtasks',{}).get(action_id)

    def close_jira_subtask(self, investigation, action_id, message):
        '''
        Close a Jira sub task associated with ticket_id
        '''
        subtask = self.get_jira_subtask(investigation, action_id)
        if not subtask:
            logging.warning("Did not find a matching sub task to close for inv ID: {} action ID: {}".format(investigation.id, act_id_action.id))
            return
        logging.info("Closing sub task ID: {}".format(subtask))
        issue = self.jira.issue(subtask)
        if message:
            self.jira.add_comment(issue.key, message)
        self.jira.transition_issue(issue, transition='Done')

    def _make_rem_action_message(self, action):
        '''
        Make a Jira message from a remediation action
        '''
        md = "*Action*\n"
        md += action.action
        if action.comment:
            md += "\n*Comment*\n"
            md += action.comment
        if action.detail_markdown:
            md += "\n*Details*\n"
            md += action.detail_markdown
        if action.remediation_action_assets:
            md += "\n*Assets*\n"
            for asset in action.remediation_action_assets:
                if asset.asset_type != "DEVICE":
                    md += "- {}\n".format(asset.value)
        return md

    def sync_remediation_actions(self):
        '''
        Retrieve remediation actions created since last poll and ensure they
        have sub tasks created for them
        '''
        for act in self.workbench.remediation_actions.search(updated_at=gt(self.poll_since.isoformat())):
            logging.info("Syncing remediation action ID: {} created at: {}".format(act.id, act.updated_at))
            ticket_id = self.create_jira_ticket(act.investigation)
            if act.status == 'IN_PROGRESS':
                logging.info("Creating task from remediation action ID: {}".format(act.id))
                self.create_jira_subtask(act.investigation, act.id, ticket_id, act.action, self._make_rem_action_message(act))
            else:
                logging.info("Closing task from remediation action ID: {}".format(act.id))
                self.close_jira_subtask(act.investigation, act.id, act.close_reason)

    def sync_wb_comments(self):
        '''
        Retrieve remediation actions created since last poll and ensure they
        have sub tasks created for them
        '''
        for cmt in self.workbench.comments.search(created_at=gt(self.poll_since.isoformat())):
            logging.info("Syncing expel comment ID: {}".format(cmt.id))
            ticket_id = self.get_ticket_for_investigation(cmt.investigation)
            if not ticket_id:
                logging.warning("There is no ticket for this investigation, skipping comment create for comment ID: {} inv ID: {}".format(cmt.id, cmt.investigation.id))
                continue
            self.create_jira_comment(cmt.investigation, ticket_id, cmt)

    def create_jira_comment(self, investigation, ticket_id, comment):
        '''
        Create a comment in Jira from a Workbench comment
        '''
        if investigation.properties and comment.id in investigation.properties.get('jira-comments',{}):
            logging.info("Comment already added to ticket for comment id: {}".format(comment.id))
            return

        msg = "New comment on investigation at {}:\n{{noformat}}\n".format(comment.created_at)
        msg += comment.comment
        msg += " - {}\n{{noformat}}\n".format(comment.created_by.display_name)
        j_comment = self.jira.add_comment(ticket_id, comment.comment)

        # store comment references on investigation properties
        prop = investigation.properties or {}
        comment_refs = prop.get('jira-comments',{})
        comment_refs[comment.id] = j_comment.id
        comment_refs[j_comment.id] = comment.id
        prop['jira-comments'] = comment_refs
        investigation.properties = prop
        investigation.save()
        logging.info("Created Jira comment for ticket ID: {}".format(ticket_id))



def main():
    parser = argparse.ArgumentParser(description='Sync Jira with activities in Expel Workbench')
    parser.add_argument('-s', '--start_at', required=False, default=datetime.now().isoformat(), help='Start syncing activities created after this timestamp')
    parser.add_argument('-p', '--jira_project', required=True, help='Sync Workbench activities with this JIRA project')
    args = parser.parse_args()

    syncer = JiraSyncer(auth_workbench(), auth_jira(), args.jira_project, start_at=dt_parser.parse(args.start_at))
    while True:
        logging.info("Starting sync...")
        syncer.sync()
        logging.info("Sync finished.")
        time.sleep(60)

if __name__ == '__main__':
    sys.exit(main())

