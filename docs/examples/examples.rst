.. _examples:

Usage and Example use cases
===========================

Before diving into example use cases, it’s important to grasp the basics of the pyexclient. The basics will allow you to implement your own custom use cases. 

.. _usage basics:
   
The basics
----------
Every resource type supported by Expel Workbench is implemented as a python class in pyexclient. The base resource type class has four methods implemented along with a context handler and iter method. Understanding how to use these concepts will make you a rockstar (sorry had to) when it comes to building or improving your automated use cases. Let’s walk through each method in detail.

All code snippets below assume you’ve :ref:`authenticated <snippet auth>` and have the authenticated pyexclient in the variable ``x``. 

.. _basic create:

create(...)
^^^^^^^^^^^
The create method is used to create new instances of a resource type. You can see examples of this :ref:`create comment <snippet create comment>`, or :ref:`create investigation <snippet create investigation>`.  You must call `save()` for changes/creations to be written back to the server.
Every attribute for the given resource type can be specified (via its field name) as a named parameter to the create method. In addition to specifying the values of attributes for a specific resource type, you can also specify relationships when creating a new resource type. To specify a relationship when creating a new resource type you’ll prepend ``relationship_`` and then relationship name. The value is going to be the identifier to the already existing resource type that the relationship will link to. Some relationships are required when creating a new instance of a resource type. Let’s look at a sample:

.. code-block:: python

    ACTOR_ID = "5ac919dd-352d-4cde-a5b3-c0c3ed77a318" # Current User ID
    CUSTOMER_ID = "d44fcb09-90e3-44a2-831e-f381aaec37f5" # Customer ID
    inv = x.investigations.create(title="New Incident", relationship_organization=CUSTOMER_ID, is_incident=True, analyst_severity="MEDIUM",  relationship_assigned_to_actor=ACTOR_ID)
    inv.save()

The above snippet creates an incident with a severity of `Medium`, title of `New Incident` that is assigned to `ACTOR_ID`. The other way to create a new instance is:

.. code-block:: python

    ACTOR_ID = "5ac919dd-352d-4cde-a5b3-c0c3ed77a318" # Current User ID
    CUSTOMER_ID = "d44fcb09-90e3-44a2-831e-f381aaec37f5" # Customer ID
    inv = x.investigations.create(title="New Incident", is_incident=True)
    inv.relationship.organization = CUSTOMER_ID
    inv.relationship.assigned_to_actor = ACTOR_ID
    inv.save()

This snippet accomplishes the same thing as above but to some maybe easier to read.


get(...)
^^^^^^^^
The get method is used when you already know the identifier of the existing resource instance you want to retrieve. Once you’ve retrieved the resource instance you can read and/or modify the resource instance’s attributes. 

.. code-block:: python

    inv = x.investigations.get(id="22adb298-1e9e-424c-a754-b8ab09f38282")
    inv.title = "New Title"
    inv.save()

The above snippet changes the title of the investigation. You must call `save()` to have changes written back to the Expel Workbench. Otherwise the changes are just local and useless.


save(...)
^^^^^^^^^
This method will POST any changes to the resource instance back to the Expel Workbench. If you do not call this method after making modifications the modifications will not be reflected in Expel Workbench.

search(...)
^^^^^^^^^^^
Understanding this method means you can easily access resource instances that meet complex criteria without having to iterate through tons of data. The search method pushes the filtering logic to the server side for evaluation and only returns instances that matched the criteria. There are six useful operators to be aware of when building search criteria. Let’s walk through examples of each:

neq()
"""""
This operator will return resource instances where the specified attribute is not equal to the value provided to filter_by.

.. code-block:: python

    for rem_act in x.remdiation_actions.search(status=neq("CLOSED")):
        print(f"Recommended remediation action is {rem_act.action} the status is {rem_act.status}")

In the snippet above we’re searching for any remediation action that is not currently closed. Then we print the remediation action text and the current status. 


contains()
""""""""""
.. warning:: Partial matches are not indexed and API performance can be impacted by doing a lot of these requests. Investigative data is indexed and optimized for searching, but you must use search=flag("term").


This operator will do a substring search (“partial match”) on a given attribute’s value and return the resource instances that have a partial match. This search operation is case insensitive. This operator will return resource instances where the specified attribute is equal to the value provided to filter by.

.. code-block:: python

    for cmt in x.comments.search(comment=contains("oops")):
        print(f"Found comment with word oops in it {cmt.comment}")

The above snippet will search all comments in Expel Workbench and return any instance where the comment contains the word "oops."


startswith()
""""""""""""
This operator will return instances of resources where the value of a specified attribute starts with the provided text.

.. code-block:: python

    for cmt in x.comments.search(comment=startswith("hey")):
        print(f"Found comment that starts with hey ‘{cmt.comment}’")


isnull(), notnull()
"""""""""""""""""""
It allows you to search for instances where a specified attribute is null or not null. 

.. code-block:: python

    for rem_act in x.remdiation_actions.search(status=isnull()):
        print(f"Recommended remediation action is {rem_act.action} the status is null")

    for rem_act in x.remdiation_actions.search(status=notnull()):
        print(f"Recommended remediation action is {rem_act.action} the status is not null")


gt(), lt(), window()
""""""""""""""""""""
You can specify a field should be greater than, and/or less than a value by using the ``gt()`` or ``lt()`` operators respectively. To do searches over a range or window you’ll use the ``window()`` operator.

.. code-block:: python

    start_date = (datetime.datetime.now()-datetime.timedelta(days=1)).isoformat()

    for cmt in x.comments.search(comment=startswith("hey"), created_at=gt(start_date)::
        print(f"Found comment in past 24 hours that starts with hey ‘{cmt.comment}’")

The above snippet looks for comments starting with the word “hey” that were created in the past 24 hours. 
 

.. code-block:: python

    end_date = datetime.datetime.now().isoformat()

    for cmt in x.comments.search(comment=startswith("hey"), created_at=lt(end_date)
         print(f"Found comment in past 24 hours that starts with hey ‘{cmt.comment}’")

The above snippet does the same thing looking for comments created at a timestamp less than the current time. Finally the window operator:

.. code-block:: python

    start_dt = (datetime.datetime.now()-datetime.timedelta(days=3)).isoformat()
    end_date = (datetime.datetime.now()-datetime.timedelta(days=1)).isoformat()

    for cmt in x.comments.search(created_at=window(start_dt, end_date), comment=startswith("hey")):
         print(f"Found comment in past 2 days that starts with hey ‘{cmt.comment}’")

This example looks for comments created in past two days that start with “hey”. The window operator supports strings, integers and datetime objects.

flag()
""""""
Our API supports a custom query parameter called flag. Flag allows callers to pass variables to the backend. Flags are defined on a resource by resource basis, and will alter the behavior of a given API call. The most commonly used flag parameter will be "search" which will search investigative data in a highly optimized way.

.. code-block:: python

    for inv in x.investigations.search(search=flag("ransomware")):
        print(f"Incident related to ransomware: {inv.title}")

limit()
"""""""
The API supports a limit operator that will limit the number of results returned by the server in each requested page. This can be used when you you are calling an API and you only need, or care about one result. Note if you iterate over responses, you will continue to request pages with this specified size. Pair this operator with one_or_none() to retrieve a single resource.

.. code-block:: python

    inv = x.investigations.search(limit(1)).one_or_none()
    print(f"Investigation: {inv.title}")


relationship(...)
^^^^^^^^^^^^^^^^^
Sometimes you may want to work with a resource type, but you want to filter based on criteria applied to another resource type that it has a relationship to. This is most common when you are wanting to filter resource type objects that are voluminous like investigative actions. You can specify you’re wanting to filter on a relationship resource type by using the relationship operator. Let’s look at a few examples:

.. code-block:: python

    start_date = (datetime.datetime.now()-datetime.timedelta(days=1)).isoformat()
    for inv_act in x.investigative_actions.search(relationship("investigation.created_at", gt(start_date)), action_type="MANUAL"):
        print(f"Found investigative action associated with manual investigation created in the past 24 hours {inv_act.title}")

This snippet applies filtering criteria to two attributes. The action_type attribute lives in the investigative_action resource type and filters out any investigative action that is not manually created. The next filter is applied to investigation resource type. In this case there’s a relationship between investigations and investigative actions. This scopes what search returns to investigative actions that are associated with investigations that have been created in the past 24 hours. 

Context Handler
^^^^^^^^^^^^^^^
There’s a context handler implemented for all resource types. It makes it easy to savechanges to existing resource instances. It can be used by specifying the resource type as a property in conjunction with a call to the get method().

.. code-block:: python

    with x.investigations.get(id="53212cd8-475e-442e-8102-28d20ca33246") as inv:
        inv.title = "New Updated Title"

This will update the investigation with a new title and save it back to the API.



Iteration / Pageination
^^^^^^^^^^^^^^^^^^^^^^^

Iterating over all the instances of any resource type is as simple as a for loop. 

.. code-block:: python

    for expel_alert in x.expel_alerts:
        print(f"Expel Alert {expel_alert.expel_name}")

Pyexclient will handle the pagination of results and will yield each instance in the for loop. This allows for easy implementation of filtering logic on the client side should you so desire. 

.. code-block:: python

    for expel_alert in x.expel_alerts:
        if expel_alert.expel_severity != "HIGH":
            continue
        print(f"Expel Alert {expel_alert.expel_name}")

The above snippet only prints Expel alerts with `HIGH` severity. You could also implement this with ``search(expel_severity="HIGH")``. 


Helpers
-------
Pyexclient contains a number of helper methods that can be useful when performing common tasks. 

Before diving into the helper methods, it’s important to understand a little bit about Investigative Actions within Expel Workbench since the helper functions operate on investigative actions. 

**Background on Investigative Actions**

Investigative actions are most commonly actions run by Expel’s automated systems or analysts during the course of alert triage and/or during investigations/incidents. The actions type and parameters specified to the investigative action tell Expel’s backend integration and tasking infrastructure to go gather specific types of data. 

The acquired data is usually summarized and relevant information presented to the analyst and/or customer. The raw data can be downloaded from within Workbench, or viewed using Expel Workbench’s built-in data viewer.

download(...)
^^^^^^^^^^^^^
Sometimes when you’re automating tasks or integrating systems, you’ll want the ability to access the raw data that the investigative action collected. This helper function makes downloading data from an investigative action easy. This can only be called on investigative action resource types. 

.. code-block:: python

    with x.investigative_actions.get(id=inv.act_id) as ia:
        with tempfile.NamedTemporaryFile() as fd:
              ia.download(fd)
              pprint.pprint(json.loads(fd.read()))
        
The above example will download and print the JSON data backing the investigative action (``inv.act_id``). 

create_auto_inv_action(...)
^^^^^^^^^^^^^^^^^^^^^^^^^^^
This helper function will automate the creation (subsequent execution) of an investigative action associated with a security device. This is how you can automate investigative tasks that are backed by Expel’s integration with a security vendor.

.. code-block:: python

    ia = x.create_auto_inv_action(
        title='Query SIEM for activity involving 1.2.3.4',
        input_args={'query':'"1.2.3.4"',
                   'start_time':'2020-09-03T13:38:19.539071',
                   'end_time':'2020-09-03T16:38:19.539071'},
        capability_name='query_logs',
        vendor_device_id='my-vendor-device-guid',
        customer_id='my-organization-guid',
        reason='To see what else happened involving this IP.',
        created_by_id='my-actor-id',
        investigation_id='my-investigation-id',
    )

 
In the above example, we ran an investigative action “Query Logs” which will query the security device for activity involving 1.2.3.4.

create_manual_inv_action(...)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
This helper function will create a manual investigative action associated with an investigative action. Manual actions can be used to record investigative questions and answers that analysts wish to associate with an investigation. 

.. code-block:: python

    ia = xc.create_manual_inv_action(
        title = "Investigate suspicious url evil.com", 
        reason = "Research evil.com to see if it is actually suspicious.",
        instructions = "Investigate open source intel to gather additional details",
        Investigation_id = "my-investigation-id")
     
In the above example, we created a manual investigative action to investigate a suspicious URL. Once created, the action can serve as a placeholder for our results once we’ve gathered the relevant data. To complete the action, we can close it with results like so:

.. code-block:: python

    ia.status = "COMPLETED"
    ia.results = "I investigated this URL and found it was not suspicious."
    ia.save()



capabilities(...)
^^^^^^^^^^^^^^^^^
The capabilities helper function can be used to determine what automatic actions are possible for your organization based on the currently on-boarded integrations.

.. code-block:: python

    x.capabilities("my-organization-id")




Examples 
--------
We've provided examples based on what we’ve heard about from customers who are wanting to further integrate with our platform. There are three types of examples we've documented.

1. :ref:`Snippet <snippets>` - This is code self contained in the documentation. Usually just a few lines.
2. :ref:`Script <scripts>` - This is a whole python script that accomplishes the use cases. A brief description on each script is provided. The scripts themselves are in examples/ directory. 
3. :ref:`Notebook <notebooks>` - A jupyter notebook that implements, mostly experimental concepts that forward leaning customers might be interested in. 


.. toctree::
   :maxdepth: 2

   snippets
   scripts 
   notebooks

