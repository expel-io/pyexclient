.. _usecases:


.. _snippet auth:
   
Snippet: Authentication 
------------------------

There are two ways to authenticate to Expel Workbench. The first is as a user with your password and MFA token, the second is with an API key. To authenticate as a user, you’ll need to provide your password and your 2FA code.

.. code-block:: python

    import getpass
    print("Enter Username:")
    username = input()
    print("Enter Password:")
    password = getpass.getpass()
    print("2FA Code:")
    code = input()

    x = WorkbenchClient('https://workbench.expel.io', username=username, password=password, mfa_code=code) 
    for vendor in x.vendors:
        print(vendor.name)

To authenticate with an api key: 

.. code-block:: python

    x = WorkbenchClient('https://workbench.expel.io', apikey='apikey')


.. _snippet list remediation:

Snippet: List all open remediation actions
------------------------------------------

Sometimes it can be useful to review all open remediation actions. This is a snippet of examples/open_remediation_actions.py will list all remediation actions
that are not currently completed or closed. You can optionally specifiy a date range to scope the search too.

.. literalinclude:: ../../examples/open_remediation_actions.py 
     :language: python 
     :caption:  examples/open_remediation_actions.py
     :name: open_remediation_actions.py
     :lines: 25-38
     :dedent: 4


.. _snippet device name:

Snippet: Return device name of security device ID
-------------------------------------------------
Working with identifiers can be helpful, but also hard to mentally keep track of at times. This example is a simple function to return the human readable name of a security device ID

.. code-block:: python

    def security_device_to_name(xc, device_id):
        device = xc.workbench.security_devices.get(id=device_id)
        if device:
            return device.name
        return None

    device_id = "device-id-here"
    device_name = security_device_to_name(device_id)


.. _snippet investigative action query domain:

Snippet: Return devices with a specific investigative action support
--------------------------------------------------------------------
Before starting an investigative action, it is sometimes helpful to look up the capabilities of your onboarded devices to make sure you have a device that supports a particular investigative action. This example will use Capabilities to look for `ENDPOINT` devices, such as EDR or antivirus devices, that support the Query Domain capability.

.. code-block:: python

    def get_query_domain_devices(xc):
        endpoint = xc.workbench.capabilities(customer_id).get("ENDPOINT")
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

Iterate over all the investigations and print their status.



.. _snippet list comments:

Snippet: List comments 
----------------------

List all comments

.. _snippet create comment:

Snippet: create comment
-----------------------

Create a comment


Snippet: Listing Investigative Actions
--------------------------------------

There are two ways to list investigative actions by customer, and subsequently filtering on type.


Or you can do this to just filter on MANUAL for example.




.. _snippet top investigative actions:

Snippet: Find top Investigative Actions 
---------------------------------------

Find the top 10 investigative actions by number of times they are issued.


.. _snippet create investigation:

Snippet: Creating new investigation 
-----------------------------------

Create a new investigation in Workbench.

Or 

.. _snippet list open investigations:

Snippet: List open investigation 
--------------------------------

List open investigations in Workbench.



.. _snippet close investigation:

Snippet: Close an investigation 
-------------------------------

Update an investigation’s state by closing it.




.. _snippet create investigation findings:

Snippet: Creating investigation findings 
----------------------------------------

Create new findings text for an investigation.


.. _snippet modify investigation findings:

Snippet: Modify investigation findings 
--------------------------------------

Modify findings text for an investigation.



.. _snippet create auto investigative action:

Snippet: Create an investigative action and poll for completion
---------------------------------------------------------------

Create "auto" investigative actions, using our tasking framework. This example will use the Query Logs investigative action. After creating the investigative action shows how to download the results. Assumes the results completed. Requires knowing the following values: - Investigation ID - A user ID, can also use customer ID in place of a specific user - Vendor device ID to task - Input arguments to the "task" defined per capability - Query that is specific to the SIEM we are talking too. This example works on Sumo Logic.



.. _snippet upload investigative data:

Snippet: Upload investigative data 
----------------------------------

While uncommon, it can happen that a customer has access to logs or data that we don’t. In that case it’s important Expel gain access to that data to help complete an investigation. In this example we’ll show how you can upload arbitrary data associated with an investigation.


.. _snippet return investigations closed as pup:

Snippet: Return investigations closed as PUP/PUA 
------------------------------------------------

Investigation close decisions can be helpful to identify certain types of investigations or incidents identified in your organization. This example will find investigations with a close decision of PUP/PUA.

.. _snippet interact hunt investigation:

Snippet: Interacting with Expel hunting investigations
------------------------------------------------------
Note: Hunting investigations are specific to the Expel Hunting service and available to those who have purchased this option. 

.. _snippet device name to device id:

Snippet: Return device name of security device ID
-------------------------------------------------
Working with identifiers can be helpful, but also hard to mentally keep track of at times. This example is a simple function to return the human readable name of a security device ID

.. _snippet devices specific action:

Snippet: Return devices with a specific investigative action support
--------------------------------------------------------------------
Before starting an investigative action, it is sometimes helpful to look up the capabilities of your onboarded devices to make sure you have a device that supports a particular investigative action. This example will use Capabilities to look for `ENDPOINT` devices, such as EDR or antivirus devices, that support the Query Domain capability.

.. _snippet close remediation action:

Snippet: Close a remediation action as completed
------------------------------------------------
Update a remediation action as completed, and close it in Expel Workbench.
<snippet>

.. _script list all ips:

Script: List all Destination IPs from Expel Alerts
--------------------------------------------------
There’s a fully documented script located in examples/list_dest_ip.py. This script will write a CSV containing timestamp of alert, expel alert name, security device and destination ip for all Expel alerts in the past year. 

.. _script poll for ransomware:

Script: Poll for ransomware Incidents
-------------------------------------
There’s a fully documented script located in examples/poll_ransomware_incidents.py. This script will poll Expel Workbench for any incidents created in the past five minutes that involved ransomware. The script will extract the asset ID (if provided by the EDR) and print that to screen. It’s the starting point for customers who are interested in SOAR integration. 

.. _script bidirectional jira:

Script: Bi-Directional State (JIRA)
-----------------------------------
This script will sync state between JIRA tickets and Expel Workbench. It’ll sync the following to JIRA from Expel Workbench:

* Investigative Actions details and outcome as sub tasks
* Investigation description, lead alert
* Investigative comments
* Incident findings
* Investigation status closed/opened

It’ll sync to Workbench:

* Investigative comments
* Ticket status closed/open

