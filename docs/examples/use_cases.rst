.. _usecases:


.. _snippet auth:

Snippet: Authentication
------------------------

There are two ways to authenticate to Expel Workbench. The first is as a user with your password and MFA token, the second is with an API key. To authenticate as a user, you’ll need to provide your password and your 2FA code.

.. code-block:: python

    import getpass
    from pyexclient import WorkbenchClient

    print("Enter Username:")
    username = input()
    print("Enter Password:")
    password = getpass.getpass()
    print("2FA Code:")
    code = input()

    xc = WorkbenchClient('https://workbench.expel.io', username=username, password=password, mfa_code=code)

To authenticate with an api key:

.. code-block:: python

    xc = WorkbenchClient('https://workbench.expel.io', apikey='apikey')

.. _snippet list remediation:

Snippet: List all open remediation actions
------------------------------------------

Sometimes it can be useful to review all open remediation actions. This is a snippet of `Open Remediation Actions <https://github.com/expel-io/pyexclient/blob/master/examples/open_remediation_actions.py>`_ will list all remediation actions
that are not currently completed or closed. You can optionally specifiy a date range to scope the search too.

.. literalinclude:: ../../examples/open_remediation_actions.py
     :language: python
     :caption:  examples/open_remediation_actions.py
     :name: open_remediation_actions.py
     :lines: 42-61
     :dedent: 4

.. _snippet device name:

Snippet: Return device name of security device ID
-------------------------------------------------
Working with identifiers can be helpful, but also hard to mentally keep track of at times. This example is a simple function to return the human readable name of a security device ID

.. code-block:: python

    def security_device_to_name(xc, device_id):
        device = xc.security_devices.get(id=device_id)
        if device:
            return device.name
        return None

    device_id = "158b031d-87f8-4c42-80ee-f9fb15796360"
    device_name = security_device_to_name(xc, device_id)

.. _snippet investigative action query domain:

Snippet: Return devices with a specific investigative action support
--------------------------------------------------------------------
Before starting an investigative action, it is sometimes helpful to look up the capabilities of your onboarded devices to make sure you have a device that supports a particular investigative action. This example will use Capabilities to look for `ENDPOINT` devices, such as EDR or antivirus devices, that support the Query Domain capability.

.. code-block:: python

    def get_query_domain_devices(xc):
        endpoint = xc.capabilities().get("ENDPOINT")
        if endpoint:
            query_domain = endpoint.get("query_domain")
            if query_domain:
                security_devices = query_domain.get("security_devices")
                if security_devices:
                    return security_devices
        return None

    query_domain_devices = get_query_domain_devices(xc)

.. _snippet list investigations:

Snippet: Listing investigations
-------------------------------

Iterate over all the investigations and print their title and status.

.. code-block:: python

    for inv in xc.investigations:
        s = "Investigation ID: {inv_id} Title: {inv_title} Status: {inv_status}"
        status = "OPEN" if inv.close_comment is not None else "CLOSED"
        print(s.format(inv_id=inv.id, inv_title=inv.title, inv_status=status))

.. _snippet list comments:

Snippet: List comments
----------------------

List all comments, displaying when they were created and by which user.

.. code-block:: python

    for comment in xc.comments:
        s = "[{ts}] {cmt} - {user}"
        print(s.format(ts=comment.created_at, cmt=comment.comment, user=comment.created_by.display_name))

.. _snippet create comment:

Snippet: create comment
-----------------------

Create a comment and associate it with an investigation.

.. code-block:: python

    comment = xc.comments.create(comment="Hello world!")
    comment.relationship.investigation = 'my-investigation-id'
    comment.save()

Snippet: Listing Investigative Actions
--------------------------------------

List investigative actions by type or capability name.

For example, listing all manual (human driven) investigative actions:

.. code-block:: python

    for inv_act in xc.investigative_actions.search(action_type='MANUAL'):
        print(inv_act)

Alternatively, you could search for all automatic actions to acquire a file like this:

.. code-block:: python

    for inv_act in xc.investigative_actions.search(capability_name='acquire_file'):
        print(inv_act)

.. _snippet top investigative actions:

Snippet: Find top automatic Investigative Actions
---------------------------------------

Find the top 10 automatic investigative actions by number of times they are issued.

.. code-block:: python

    from collections import defaultdict

    # Retrieve all automatic actions
    actions = defaultdict(int)
    for action in xc.investigative_actions.search(action_type='TASKABILITY'):
        actions[action.capability_name] += 1

    # Sort and list top 10 actions
    top_actions = sorted(actions.items(), key=lambda x: x[1], reverse=True)
    top_actions[:10]

.. _snippet create investigation:

Snippet: Creating new investigation
-----------------------------------

Create a new investigation in Workbench.

.. code-block:: python

    inv = xc.investigations.create(title='My investigation title')
    inv.save()

.. _snippet list open investigations:

Snippet: List open investigation
--------------------------------

List open investigations in Workbench.

.. code-block:: python

    from pyexclient.workbench import notnull

    for inv in xc.investigations.search(close_comment=notnull()):
        print(inv)

.. _snippet close investigation:

Snippet: Close an investigation
-------------------------------

Update an investigation’s state by closing it. Note that setting an investigation's close comment to anything other than None will close it.

.. code-block:: python

    with xc.investigations.get(id='my-investigation-id') as inv:
        inv.close_comment = "This is a false positive."

.. _snippet create investigation findings:

Snippet: Creating findings for an incident
----------------------------------------

Create new investigative findings for an incident.

.. code-block:: python

    finding = xc.investigation_findings.create(
        rank = 1, # The order in which this finding will appear in Workbench
        title = "Where else is it?", # Title of the finding
        finding = "We found it **EVERYWHERE!**", # Markdown body for the finding
    )
    finding.relationship.investigation = 'my-investigation-id'
    finding.save()

.. _snippet modify investigation findings:

Snippet: Modify investigation findings
--------------------------------------

Modify findings text for an investigation.

.. code-block:: python

    with xc.investigation_findings.get(id='my-finding-id') as finding:
        finding.finding = "Updated: Turns out it wasn't _everywhere_..."

.. _snippet create auto investigative action:

Snippet: Create an investigative action and poll for completion
---------------------------------------------------------------

Create "auto" investigative actions, using our tasking framework. This example will use the Query Logs investigative action. After creating the investigative action shows how to download the results. Assumes the results completed. Requires knowing the following values: - Investigation ID - A user ID, can also use customer ID in place of a specific user - Vendor device ID to task - Input arguments to the "task" defined per capability - Query that is specific to the SIEM we are talking too. This example works on Sumo Logic.

.. code-block:: python

        import time
        from io import BytesIO
        from datetime import datetime, timedelta

        input_args = dict(
            query="evil.exe",
            start_time=(datetime.now() - timedelta(days=1)).isoformat(),
            end_time=datetime.now().isoformat(),
        )

        action = xc.create_auto_inv_action(
            vendor_device_id='my-vendor-device-id',
            capability_name='query_logs',
            input_args=input_args,
            title="Query Sumo Logic for some logs",
            reason="I want to see if I can find some logs...",
            investigation_id='my-investigation-id'

        )

        while action.status == 'RUNNING':
            print("Waiting for results...")
            time.sleep(3)
            action = xc.investigative_actions.get(id=action.id)

        if action.status == 'READY_FOR_ANALYSIS':
            results = io.BytesIO()
            action.download(results)
            results.seek(0)

            with open("results.json", 'wb') as fd:
                fd.write(results.read())
            print("Got results! Saved to results.json")
        else:
            print("No results... {status}".format(status=action.status))

.. _snippet upload investigative data:

Snippet: Upload investigative data
----------------------------------

While uncommon, it can happen that a customer has access to logs or data that we don’t. In that case it’s important Expel gain access to that data to help complete an investigation. In this example we’ll show how you can upload arbitrary to an investigation.

.. code-block:: python

    # create an manual investigative action
    action = xc.investigative_actions.create(
        action_type='MANUAL',
        title='Upload file',
        reason='To provide a file to Expel for analysis',
        status='READY_FOR_ANALYSIS',
    )
    action.save()

    # read an upload a file
    fname = 'evil.exe'
    with open(fname, 'rb') as fd:
        action.upload(fname, fd.read())

.. _snippet return investigations closed as pup:

Snippet: Return Expel Alerts closed as PUP/PUA
------------------------------------------------

Expel Alert close decisions can be helpful to identify certain types of alerts in your organization. This example will find alerts with a close decision of PUP/PUA.

.. code-block:: python

    for ea in xc.expel_alerts.search(close_reason='PUP_PUA'):
        print(ea)

.. _snippet interact hunt investigation:

Snippet: Interacting with Expel hunting investigations
------------------------------------------------------
Note: Hunting investigations are specific to the Expel Hunting service and available to those who have purchased this option.

.. code-block:: python

    for inv in xc.investigations.search(source_reason="HUNTING"):
        print(inv)

.. _snippet devices specific action:

Snippet: Return devices with a specific investigative action support
--------------------------------------------------------------------
Before starting an investigative action, it is sometimes helpful to look up the capabilities of your onboarded devices to make sure you have a device that supports a particular investigative action. This example will use Capabilities to look for `ENDPOINT` devices, such as EDR or antivirus devices, that support the Query Domain capability.

.. code-block:: python

    capabilities = xc.capabilities()
    supported = capabilities.get('ENDPOINT',{}).get('query_domain',{}).get('security_devices')
    if supported:
        print("Devices supporting this capability: ",supported)
    else:
        print("No devices support this capability")

.. _snippet close remediation action:

Snippet: Close a remediation action as completed
------------------------------------------------
Update a remediation action as completed, and close it in Expel Workbench.

.. code-block:: python

    with xc.remediation_actions.get(id='remediation_action_id') as action:
        action.status = 'COMPLETED'
        action.close_reason = 'We remediated this sytem.'

.. _script list all ips:

Script: Export Expel Alerts with Evidence Fields
--------------------------------------------------
See the example script `Export Expel Alert Evidence <https://github.com/expel-io/pyexclient/blob/master/examples/export_expel_alert_evidence.py>`_. This script will write a CSV containing timestamp of alert, expel alert name, vendor name,  and associated evidence fields.

.. _script poll for ransomware:

Script: Poll for new Incidents
-------------------------------------
See the example script `Poll For New Incidents <https://github.com/expel-io/pyexclient/blob/master/examples/poll_incidents.py>`_. This script will poll Expel Workbench for any incidents created in the past five minutes.

.. _script bidirectional jira:

Script: Bi-Directional State (JIRA)
-----------------------------------
See the example script `Jira Sync <https://github.com/expel-io/pyexclient/blob/master/examples/jira_sync.py>`_. This script will sync state between JIRA tickets and Expel Workbench. It’ll sync the following to JIRA from Expel Workbench:

* Investigative Actions details and outcome as sub tasks
* Investigation description, lead alert
* Investigative comments
* Incident findings
* Investigation status closed/opened
