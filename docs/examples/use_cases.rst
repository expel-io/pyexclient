.. _usecases:

Example use cases
=================

This section outlines very common use cases we’ve heard about from customers wanting to further integrate with our platform. There are three types of examples documented in this section.

1. Snippet -- This is code self contained in the documentation. Usually just a few lines.
2. Script -- This is a whole python script that accomplishes the use cases. A brief description on each script is provided. The scripts themselves are in examples/ directory. 
3. Notebook - A jupyter notebook that implements, mostly experimental concepts that forward leaning customers might be interested in. 

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



Example 2: List All Vendors 
-------------------------------------------------

List all the vendor names, that Expel currently integrates with.

.. code-block:: python

    x = XClient.workbench('https://workbench.expel.io', apikey='1b88d7b9-d22d-4f78-a94a-9da05ab94a81')
    for vendor in x.vendors:
        print(vendor.name)


Example 3: Listing investigations by customer 
-------------------------------------------------

Iterate over all the investigations for a specific customer and count the number investigations, and incidents that customer has.


.. code-block:: python

    x = XClient.workbench('https://workbench.expel.io', apikey='1b88d7b9-d22d-4f78-a94a-9da05ab94a81')
    # Count all investigations a customer has, and number of incidents
    inc_count = 0 # Incident count
    inv_count = 0 # Investigation Count
    for inv in x.investigations.filter_by(customer_id='c2510e19-be36-4fbd-9567-b625d57c720f'):
        if inv.is_incident:
            inc_count += 1
        else:
            inv_count += 1

    print("There were %d incidents, and %d investigations" % (inc_count, inv_count))



Example 4: Listing Investigative Actions by Customer/Type 
----------------------------------------------------------

There are two ways to list investigative actions by customer, and subsequently filtering on type.

.. code-block:: python

    x = XClient.workbench('https://workbench.expel.io', apikey='1b88d7b9-d22d-4f78-a94a-9da05ab94a81')

    man_cnt = 0
    wb_cnt = 0
    for inv in x.investigations.filter_by(customer_id='c2510e19-be36-4fbd-9567-b625d57c720f'):
        for act in x.investigative_actions.filter_by(investigation_id=inv.id):
            if act.action_type == 'MANUAL':
                man_cnt +=1
            else:
                wb_cnt += 1

    print("There were %d manual investigative actions, and %d workbench investigative actions" % (man_cnt, wb_cnt))

Or you can do this to just filter on MANUAL for example.

.. code-block:: python

    x = XClient.workbench('https://workbench.expel.io', apikey='1b88d7b9-d22d-4f78-a94a-9da05ab94a81')

    man_cnt = 0
    for inv in x.investigations.filter_by(customer_id='c2510e19-be36-4fbd-9567-b625d57c720f'):
        for act in x.investigative_actions.filter_by(action_type='MANUAL', investigation_id=inv.id):
            man_cnt +=1

    print("There were %d manual investigative actions" % man_cnt)


Example 5: Find top Investigative Actions 
-------------------------------------------------

Find the top 10 investigative actions by number of times they are issued.

.. code-block:: python

    x = XClient.workbench('https://workbench.expel.io', apikey='1b88d7b9-d22d-4f78-a94a-9da05ab94a81')
    stats = defaultdict(int)
    for act in x.investigative_actions:
        stats[act.title] += 1

    i = 0
    for title, cnt in sorted(stats.items(), key=lambda x: x[1], reverse=True):
        print("Top investigative actions %s => %d" % (title,cnt))
        i+=1
        if i > 10:
            break



Example 6: Creating new investigation 
-------------------------------------------------

Create a new investigation in Workbench.

.. code-block:: python

    x = XClient.workbench('https://workbench.expel.io', apikey='1b88d7b9-d22d-4f78-a94a-9da05ab94a81')
    i = x.investigations.create(title='Investigative Title', relationship_customer='c2510e19-be36-4fbd-9567-b625d57c720f', relationship_assigned_to_actor='c2510e19-be36-4fbd-9567-b625d57c720f')
    i.save()

Or 

.. code-block:: python

    x = XClient.workbench('https://workbench.expel.io', apikey='1b88d7b9-d22d-4f78-a94a-9da05ab94a81')
    i = x.investigations.create(title='Investigation Title')
    i.relationship.customer = CUSTOMER_GUID
    i.relationship.assigned_to_actor = CUSTOMER_GUID
    i.save()



Example 7: Creating new findings 
-------------------------------------------------

Create new findings text for an investigation.


.. code-block:: python

    x = XClient.workbench('https://workbench.expel.io', apikey='1b88d7b9-d22d-4f78-a94a-9da05ab94a81')
    i = x.investigations.create(title='Investigative Title', relationship_customer='c2510e19-be36-4fbd-9567-b625d57c720f', relationship_assigned_to_actor='c2510e19-be36-4fbd-9567-b625d57c720f')
    i.save()

    f = x.investigation_findings.create(title='What is it?', finding='It is malware.', relationship_investigation=i.id)
    f.save()


Example 8: Modifying findings 
-------------------------------------------------

Modify existing findings text for an investigation.


.. code-block:: python

    x = XClient.workbench('https://workbench.expel.io', apikey='1b88d7b9-d22d-4f78-a94a-9da05ab94a81')
    i = x.investigations.create(title='Investigative Title', relationship_customer='c2510e19-be36-4fbd-9567-b625d57c720f', relationship_assigned_to_actor='c2510e19-be36-4fbd-9567-b625d57c720f')
    i.save()

    f = x.investigation_findings.create(title='What is it?', finding='It is malware.', relationship_investigation=i.id)
    f.save()

    for f in inv.findings:
        if f.title == 'What is it?':
            with x.investigation_findings.get(id=f.id) as f1:
                f1.finding = 'foo bar baz'
                f1.save()

Example 9: Create auto investigative actions (Query User) 
-----------------------------------------------------------

Create "auto" investigative actions, using our tasking framework. This example will use the Query User investigative action.
Requires knowing the following values:
- Investigation ID
- A user ID, can also use customer ID in place of a specific user
- Vendor device ID to task
- Input arguments to the "task" defined per capability 


.. code-block:: python

    x = XClient.workbench('https://workbench.expel.io', apikey='1b88d7b9-d22d-4f78-a94a-9da05ab94a81')
    input_args = {'user_name': 'matt.peters@expel.io', 'time_range_start':'2019-01-30T14:00:40Z', 'time_range_end':'2019-01-30T14:45:40Z'}
    inv_act = x.create_auto_inv_action(customer_id, investigation_id, vendor_device_id, customer_id, 'query_user', input_args, 'Title of Inv Action', 'Reason for Inv Action') 
    print("Investigative Action ID: ", inv_act.id)

Example 10: Create auto investigative actions (Query Logs) and download results
---------------------------------------------------------------------------------

Create "auto" investigative actions, using our tasking framework. This example will use the Query Logs investigative action. After creating the investigative action shows how to download the results. Assumes the results completed..
Requires knowing the following values:
- Investigation ID
- A user ID, can also use customer ID in place of a specific user
- Vendor device ID to task
- Input arguments to the "task" defined per capability 
- Query that is specific to the SIEM we are talking too. This example works on Sumo Logic.


.. code-block:: python

    x = XClient.workbench('https://workbench.expel.io', apikey='1b88d7b9-d22d-4f78-a94a-9da05ab94a81')
    query = '_sourcecategory = "prod/cloud/skyformation" | parse "\\"email\\":\\"*\\"" as email'
    input_args = {'query': query, 'start_time':'2019-01-30T14:00:40Z', 'end_time':'2019-01-30T14:45:40Z'}

    inv_act = x.create_auto_inv_action(customer_guid, inv_guid, device_guid, me_guid, 'query_logs', input_args, 'raw query logs', 'testing one more example') 
    print("Investigative Action ID: ", inv_act.id)

    # NOTE: Need to wait or check on status before trying to download.
    with x.investigative_actions.get(id=inv_id) as ia:
        fd = tempfile.NamedTemporaryFile(delete=False)
        ia.download(fd)
        fd.seek(0)
        pprint.pprint(json.loads(fd.read()))
 


Example 11: Create, Upload data, and close a manual investigative action 
--------------------------------------------------------------------------

Create "manual" investigative actions. This means the investigative action is not backed by tasks. Upload some data associated with the manual action and then close the manual investigative action specifying some outcome.


.. code-block:: python

    x = XClient.workbench('https://workbench.expel.io', apikey='1b88d7b9-d22d-4f78-a94a-9da05ab94a81')
    inv_act = x.create_manual_inv_action(customer_id, investigation_id, created_by_id,  'title manual 1', 'reason manual 1', 'instructions 1') 
    print("Investigative Action ID: ", inv_act.id)
    inv_act.upload('file.ext', b'raw bytes')

    # TODO show example uploading results (backed by a file to manual action)

    # Context handler will "patch" changes after we exit.. pretty nifty!
    with x.investigative_actions.get(id=inv_id) as ia:
        ia.results = 'i m done here, *this is markdown bold*'
        ia.status = 'COMPLETED'



