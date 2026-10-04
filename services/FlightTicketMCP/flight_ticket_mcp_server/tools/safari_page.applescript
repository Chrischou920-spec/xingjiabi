on run arguments
    set actionName to item 1 of arguments
    set targetURL to item 2 of arguments
    set tabMarker to "#xingjiabi-live"
    tell application "Safari"
        set sourceWindow to missing value
        set managedTab to missing value
        set managedWindow to missing value
        repeat with browserWindow in windows
            repeat with browserTab in tabs of browserWindow
                set pageURL to URL of browserTab
                if pageURL is not missing value then
                    if pageURL starts with "https://flights.ctrip.com/" then
                        if sourceWindow is missing value then set sourceWindow to browserWindow
                        if pageURL ends with tabMarker then
                            set managedTab to browserTab
                            set managedWindow to browserWindow
                        end if
                    end if
                end if
            end repeat
        end repeat
        if actionName is "prepare" then
            if managedTab is missing value then
                if sourceWindow is missing value then error "SAFARI_CTRIP_TAB_REQUIRED"
                set managedTab to make new tab at end of tabs of sourceWindow with properties {URL:targetURL}
                set managedWindow to sourceWindow
            else
                set current tab of managedWindow to managedTab
                set URL of managedTab to targetURL
            end if
            -- Ctrip may defer rendering its list in an unselected Safari tab.
            -- Use the tab's own window, which may differ from sourceWindow.
            set current tab of managedWindow to managedTab
            return "ready"
        else if actionName is "read" then
            if managedTab is missing value then error "SAFARI_QUERY_TAB_CLOSED"
            if URL of managedTab is not targetURL then error "SAFARI_QUERY_TAB_CHANGED"
            return (URL of managedTab) & linefeed & (text of managedTab)
        else
            error "SAFARI_INVALID_ACTION"
        end if
    end tell
end run
