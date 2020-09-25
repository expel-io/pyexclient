.. _client:

Understanding the Client
========================
Becoming familiar with pyexclient requires understanding three main properties of the JSON API spec and how the pyexclient implements them. They are:

* :ref:`Resource Objects <resource objects>` – These are implemented as python classes. Each class is documented and referenced in the API Reference section. 
* :ref:`Attributes <attributes>` – These are updatable/readable fields per resource object. They’re implemented as python members of a class. There are certain fields that are read-only. Currently you can update them in the python class, but if you POST (try to save) those changes, they’ll fail. The documentation of each attribute calls out which fields are read-only. 
* :ref:`Relationships <relationships>` – These are specific links from one resource object to another.

.. warning:: As a user of the client you can delete any object within your tenant. Expel keeps point in time as well as daily back ups, but you’re using the **delete functionality at your own peril and risk**.


.. _resource objects:
   
Resource Objects
----------------
It’s useful to think of resource objects as logical containers for attributes and relationships. A resource object within Expel Workbench is just a data table in a database. Relationships are links to other tables and attributes are columns in a table. This intuition is helpful as we build complex tasks. 

Every resource object is documented in the API reference section. Each resource object has a table containing the following:

* Field Description – A description of the given field
* Field Name – The name of the field to reference it in code
* Field Type – The type of field it is. If the field is a relationship, this will be a hyperlink to the resource object.
* Attribute – Yes / No indicates if the field is an attribute
* Relationship – Yes / No indicates if the field is a relationship.

Pyexclient has properties representing each resource object. Each documented resource (see :ref:`API Reference section <api>`) has a resource type field. The value of this field is the property name.  So, if for example, we want to work with investigations, we would find the :ref:`Investigations <api investigations>` resource object in the API reference section and see that it is called investigations. We can then use this property to do any of the creating or retrieving. 

See examples on :ref:`creating <snippet create investigation>`, retrieving, :ref:`listing <snippet list comments>` and finding resource objects. 


.. _attributes:
   
Attributes
----------
Every resource has a set of attributes. There will always be an id, and a created_at attribute. The attributes are used by Expel Workbench UI and automated systems to reason about various activities and to reflect/updated status. 

Attributes can be used to filter down to specific resource objects that you’re interested in. See :ref:`Finding Open Investigations <snippet list open investigations>` for an example. Not sure what attributes are available for a resource object? Check out the Attribute column in the API docs for the resource. Rows where the Attribute column is “Y” indicate the given field is an attribute of the object, not a relationship to another object.

Attributes are accessible like any attribute on a python object. Changing them, and then calling the save method will write the changes back to Expel Workbench.  


.. _relationships:
   
Relationships
-------------
Relationships describe the linkage between two different resource types There are two types of relationships an resource object can have. The first is one to one, where the relationship represents a relationship to another single resource instance. The second type of relationship is one to many, where the relationship would encompass multiple resource instances.

.. note:: It’s not entirely clear from the documents which relationship is one to one versus one to many it’s something we’ll look at addressing in the future.

The most common task when working with relationships is to retrieve the full resource object referenced by the relationship. For example, let’s say we want to grab the name of the actor that is assigned to the investigation with ID ``cf9445b1-a0aa-4092-af5f-ecdc136d1661``.

.. code-block:: python

    inv = x.investigations.get(id="cf9445b1-a0aa-4092-af5f-ecdc136d1661")
    print(f"Assigned to actor name {inv.assigned_to_actor.display_name}")

This pattern will retrieve the full underlying resource referenced by the relationship assigned_to_actor, which is a relationship between a resource type of Investigation. In this case, an Investigation instance (ID = ``cf9445b1-a0aa-4092-af5f-ecdc136d1661``) and an instance of the :ref:`Actor <api actors>` resource.

In the case of a one to many relationship, where you want to retrieve the full resource object you would do the following:

.. code-block:: python

    for ea in x.expel_alerts.search(expel_severity=neq("TESTING")):
        for va in ea.vendor_alerts:
            print(va.vendor_sig_name)


In the above example, the Expel alerts resource object has a one to many relationship with vendor alerts and in this situation you’d iterate over them to see every instance that is part of that relationship. 

Sometimes you just want to know the identifier of the resource referenced by the relationship. In this example we’re just retrieving the ID for the actor assigned to our investigation. To do this you can do the following:

.. code-block:: python

    inv = x.investigations.get(id="cf9445b1-a0aa-4092-af5f-ecdc136d1661")
    print(f"Assigned to actor id {inv.relationship.assigned_to_actor.id}")


Note in the above code snippet how we use relationship, this tells pyexclient that you just want the ID for the relationship and not the full resource object. 

Modify Objects
^^^^^^^^^^^^^^

Modifying an object with pyexclient can be done by retrieving the object, updating it’s attributes and then saving the updated object. For example:

.. code-block:: python

    inv = x.investigations.get(id="myinvestigationid")
    inv.title = "My updated investigation title"
    inv.save()
 
This can also be simplified with the below syntax (which will automatically call ``.save()`` for you):

.. code-block:: python

    with x.investigations.get(id="myinvestigationid") as inv:
        inv.title = "My updated investigation title"

