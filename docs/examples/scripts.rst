.. _scripts:

.. _script list all ips:

Script: Export Expel Alerts with Evidence Fields
------------------------------------------------
See the example script `Export Expel Alert Evidence <https://github.com/expel-io/pyexclient/blob/master/examples/export_expel_alert_evidence.py>`_. This script will write a CSV containing timestamp of alert, expel alert name, vendor name,  and associated evidence fields.

.. _script poll for ransomware:

Script: Poll for new Incidents
------------------------------
See the example script `Poll For New Incidents <https://github.com/expel-io/pyexclient/blob/master/examples/poll_incidents.py>`_. This script will poll Expel Workbench for any incidents created in the past five minutes.

.. _script bidirectional jira:

Script: Sync to JIRA
--------------------
See the example script `Jira Sync <https://github.com/expel-io/pyexclient/blob/master/examples/jira_sync.py>`_. This script will sync the following to JIRA from Expel Workbench:

* Investigative Actions details and outcome as sub tasks
* Investigation description, lead alert
* Investigative comments
* Incident findings
* Investigation status closed/opened
