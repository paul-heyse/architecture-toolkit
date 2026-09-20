workspace "Synthetic qualification" "Vendor tool fixture, not generated architecture" {
    model {
        user = person "Requester"
        service = softwareSystem "Request service" {
            api = container "API" "Accept requests" "Python"
        }
        user -> service "Submits request"
        user -> api "Submits request"
    }
    views {
        systemContext service "context" {
            include *
            autoLayout lr
        }
        container service "containers" {
            include *
            autoLayout lr
        }
    }
}
