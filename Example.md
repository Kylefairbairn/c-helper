# Architecture

## Purpose

This repository provides a reusable product library for integration and system testing.

The library models embedded products, their configuration, deployment behavior, startup behavior, health checks, and runtime controls. Test suites such as `pytest` should use this library to assemble systems and run tests without needing to know product-specific launch details.

This repository is not primarily a test repository. It is the framework and product-control layer used by tests.

---

# Design Goals

The architecture should support:

- Multiple product types
- Multiple binaries per product
- Multiple configurations per product
- Multiple systems made of different products
- Local, VM, Docker, SSH, serial, and hardware execution
- Reusable pytest fixtures
- Separation of framework code from test code

Tests should answer:

> "What behavior do I want to verify?"

The framework should answer:

> "How do I deploy, configure, launch, stop, monitor, and clean up this product?"

---

# High-Level Architecture

```text
                    +----------------------+
                    |    Pytest Tests      |
                    |----------------------|
                    | test_gps.py          |
                    | test_radio.py        |
                    | test_vehicle.py      |
                    +----------+-----------+
                               |
                               |
                    Uses fixtures & APIs
                               |
                               ▼
                    +----------------------+
                    |    System Layer      |
                    |----------------------|
                    | VehicleSystem        |
                    | CommunicationsSystem |
                    | SecuritySystem       |
                    +----------+-----------+
                               |
                               |
                    Contains Products
                               |
                               ▼
                    +----------------------+
                    |    Product Layer     |
                    |----------------------|
                    | GPS                  |
                    | Radio                |
                    | Controller           |
                    | Display              |
                    | Camera               |
                    +----------+-----------+
                               |
                               |
                    Uses Runtime
                               |
                               ▼
                    +----------------------+
                    |    Runtime Layer     |
                    |----------------------|
                    | LocalRuntime         |
                    | SSHRuntime           |
                    | DockerRuntime        |
                    | VMRuntime            |
                    | SerialRuntime        |
                    | HardwareRuntime      |
                    +----------+-----------+
                               |
                               |
                    Uses Infrastructure
                               |
                               ▼
                    +----------------------+
                    | Infrastructure Layer |
                    |----------------------|
                    | SSH                  |
                    | SCP                  |
                    | Serial               |
                    | Process Runner       |
                    | Networking           |
                    | File Transfer        |
                    +----------------------+
```

---

# Repository Layout

```text
integration-framework/
│
├── framework/
│   │
│   ├── common/
│   │   ├── exceptions.py
│   │   ├── constants.py
│   │   ├── models.py
│   │   └── events.py
│   │
│   ├── config/
│   │   ├── config_loader.py
│   │   └── schemas.py
│   │
│   ├── factory/
│   │   ├── product_factory.py
│   │   └── system_factory.py
│   │
│   ├── runtime/
│   │   ├── base_runtime.py
│   │   ├── local_runtime.py
│   │   ├── ssh_runtime.py
│   │   ├── docker_runtime.py
│   │   ├── vm_runtime.py
│   │   └── serial_runtime.py
│   │
│   ├── infrastructure/
│   │   ├── ssh_client.py
│   │   ├── process_runner.py
│   │   ├── serial_client.py
│   │   └── file_transfer.py
│   │
│   ├── product/
│   │   ├── base_product.py
│   │   └── interfaces.py
│   │
│   └── system/
│       ├── base_system.py
│       └── lifecycle.py
│
├── products/
│   │
│   ├── gps/
│   │   ├── gps_product.py
│   │   ├── gps_config.py
│   │   ├── gps_health.py
│   │   └── gps_factory.py
│   │
│   ├── radio/
│   ├── controller/
│   ├── display/
│   └── camera/
│
├── systems/
│   ├── vehicle_system.py
│   ├── communication_system.py
│   └── security_system.py
│
├── configs/
│   ├── vehicle.yaml
│   └── communication.yaml
│
└── tests/
    ├── conftest.py
    ├── test_vehicle.py
    └── test_radio.py
```

---

# Product Lifecycle

Every product follows the same lifecycle.

```text
Load Configuration
        │
        ▼
Construct Product
        │
        ▼
Deploy
        │
        ▼
Configure
        │
        ▼
Start
        │
        ▼
Health Check
        │
        ▼
Ready
        │
        ▼
Run Tests
        │
        ▼
Collect Logs
        │
        ▼
Stop
        │
        ▼
Cleanup
```

---

# Base Product Interface

Every product should implement the same API.

```python
class BaseProduct:

    def configure(self):
        ...

    def deploy(self):
        ...

    def start(self):
        ...

    def stop(self):
        ...

    def restart(self):
        ...

    def health_check(self):
        ...

    def collect_logs(self):
        ...

    def cleanup(self):
        ...
```

Pytest should never know how a GPS or Radio starts internally.

---

# System Responsibilities

A System represents an entire deployment.

Example:

```text
VehicleSystem

├── GPS
├── Radio
├── Controller
└── Display
```

The system owns orchestration.

Example lifecycle:

```python
system.deploy()
system.start()
system.wait_until_ready()

yield system

system.stop()
system.cleanup()
```

Products should never start each other directly.

The System controls startup order.

Example:

```text
GPS

↓

Radio

↓

Controller

↓

Display
```

Shutdown is normally the reverse order.

---

# Runtime Layer

Products never execute commands directly.

Instead they call the runtime.

Example:

```python
runtime.run(command)

runtime.copy_file(...)

runtime.kill(...)

runtime.read_log(...)
```

Possible runtime implementations:

- Local Runtime
- SSH Runtime
- Docker Runtime
- VM Runtime
- Serial Runtime
- Hardware Runtime

The product does not care where it is running.

---

# Infrastructure Layer

Infrastructure provides low-level operations.

Examples:

- SSH
- SCP
- Serial
- subprocess
- sockets
- packet capture
- networking
- process management

Products should never use subprocess or paramiko directly.

Those belong here.

---

# Configuration

Everything should be data driven.

Example:

```yaml
products:

  gps:
    binary: build/gps
    runtime: ssh
    host: vm1
    config:
      port: 5001

  radio:
    binary: build/radio
    runtime: docker
    config:
      frequency: 225000000
```

Factories convert configuration into objects.

```python
system = SystemFactory.create("vehicle.yaml")
```

Instead of:

```python
gps = GPS(...)
radio = Radio(...)
controller = Controller(...)
```

---

# Factory Pattern

Factories own construction.

```text
Config

↓

Product Factory

↓

Products

↓

System Factory

↓

System
```

Tests should never manually construct products.

---

# Logging

Each product is responsible for collecting artifacts.

Examples:

- stdout
- stderr
- logs
- pcaps
- configuration snapshot
- crash dumps
- core files

Pytest should simply call:

```python
system.collect_logs()
```

---

# Error Handling

Use explicit exceptions.

Examples:

```text
ConfigurationError

DeployError

StartError

HealthCheckError

RuntimeError

CleanupError
```

Avoid returning False whenever possible.

---

# Dependency Direction

Dependencies only flow downward.

```text
Pytest
    │
    ▼
Systems
    │
    ▼
Products
    │
    ▼
Runtime
    │
    ▼
Infrastructure
```

Lower layers should never import higher layers.

Examples:

Infrastructure should never import Products.

Products should never import Pytest.

Runtime should never import Systems.

---

# Pytest Example

Fixture:

```python
@pytest.fixture
def vehicle():

    system = SystemFactory.create("configs/vehicle.yaml")

    system.deploy()

    system.start()

    yield system

    system.stop()

    system.cleanup()
```

Test:

```python
def test_controller_receives_gps(vehicle):

    assert vehicle.gps.health_check()

    assert vehicle.controller.received_gps()
```

Notice the test contains no deployment logic.

---

# Design Principles

- Single Responsibility Principle
- Composition over inheritance where practical
- Dependency Injection
- Factory Pattern
- Strategy Pattern for runtimes
- Strongly typed configuration
- Products are reusable
- Systems orchestrate products
- Tests verify behavior only

---

# Responsibilities

## Framework

Responsible for:

- Configuration
- Deployment
- Startup
- Shutdown
- Health Checks
- Runtime Selection
- Log Collection
- Cleanup

## Products

Responsible for:

- Product-specific behavior
- Configuration format
- Startup commands
- Shutdown commands
- Health checks
- Log collection

## Systems

Responsible for:

- Product composition
- Startup order
- Shutdown order
- Readiness
- Environment orchestration

## Tests

Responsible only for:

- Exercising behavior
- Assertions
- Validation

---

# Summary

The goal is to make integration tests read like this:

```python
def test_radio(vehicle):

    assert vehicle.radio.connected()

    assert vehicle.controller.received_packet()
```

Instead of:

```python
ssh.copy_file(...)

ssh.execute(...)

wait()

parse_logs()

check_process()

kill_process()

cleanup()
```

The framework owns deployment.

The system owns orchestration.

The products own implementation.

Pytest owns verification.
