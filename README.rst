Allow2
------

pip install allow2


Before the app/device can log any actions or check permissions/etc, you need to first "pair" the device or app:

    >>> import allow2
    >>>
    >>> userId, pairId, children = allow2.pair(user, password, deviceToken, deviceName)

The userId and pairId are used for all subsequent requests to the API and will work only while the device/app remains paired, so these values should be persisted.

If the parent that owns that account deletes the pairing, then the userId / pairId credentials will no longer work.

The "children" return value is an array of all current children definitions in that account when it is paired. You can use this to show the parent an interface to
nominate the one permanent child who will use this device/app. Alternately, you can present a selector and use the PIN on each account to allow the child to directly
select and unlock their account prior to using the device or app.

Then, to record usage and get permissions and blocks/etc, use the following:

    >>> import allow2
    >>>
    >>> ???? = allow2.log(userId, pairId, [activityId, ...], childId)

That will.... (TBC)