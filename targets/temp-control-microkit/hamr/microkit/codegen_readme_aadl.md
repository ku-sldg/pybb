# TempControlSystem::TempControlSystem.i

## AADL Architecture
|System: [TempControlSystem::TempControlSystem.i]()|
|:--|

|Thread: TempSensor::TempSensor.i |
|:--|
|Type: [TempSensor](../../aadl/packages/TempSensor.aadl#L31)<br>Implementation: [TempSensor.i](../../aadl/packages/TempSensor.aadl#L67)<br>GUMBO: [Subclause](../../aadl/packages/TempSensor.aadl#L47)|
|Periodic |

|Thread: TempControlSystem::TempControl.i |
|:--|
|Type: [TempControl](../../aadl/packages/TempControlSystem.aadl#L138)<br>Implementation: [TempControl.i](../../aadl/packages/TempControlSystem.aadl#L253)<br>GUMBO: [Subclause](../../aadl/packages/TempControlSystem.aadl#L163)|
|Periodic |

|Thread: TempControlSystem::OperatorInterface.i |
|:--|
|Type: [OperatorInterface](../../aadl/packages/TempControlSystem.aadl#L268)<br>Implementation: [OperatorInterface.i](../../aadl/packages/TempControlSystem.aadl#L299)|
|Periodic |

|Thread: CoolingFan::Fan.i |
|:--|
|Type: [Fan](../../aadl/packages/CoolingFan.aadl#L31)<br>Implementation: [Fan.i](../../aadl/packages/CoolingFan.aadl#L59)|
|Periodic |


## Rust Code


### Behavior Code
#### tempSensor: TempSensor::TempSensor.i

 - **Entry Points**


    Initialize: [Rust](crates/tsproc_tempSensor/src/component/tsproc_tempSensor_app.rs#L21)

    TimeTriggered: [Rust](crates/tsproc_tempSensor/src/component/tsproc_tempSensor_app.rs#L37)


- **APIs**

    <table>
    <tr><th>Port Name</th><th>Direction</th><th>Kind</th><th>Payload</th><th>Realizations</th></tr>
    <tr><td><a title='Model' href='../../aadl/packages/TempSensor.aadl#L38'>currentTemp</a></td>
        <td>Out</td><td>Data</td>
        <td>TempSensor::Temperature.i</td><td><a title='Rust/Verus API: Lines 33-45' href='crates/tsproc_tempSensor/src/bridge/tsproc_tempSensor_api.rs#L33'>Rust/Verus API</a> → <a title='Unverified Rust Interface: Lines 13-18' href='crates/tsproc_tempSensor/src/bridge/tsproc_tempSensor_api.rs#L13'>Unverified Rust Interface</a> → <a title='Rust/C Interface: Lines 17-22' href='crates/tsproc_tempSensor/src/bridge/extern_c_api.rs#L17'>Rust/C Interface</a> → <a title='C Extern: Line 14' href='crates/tsproc_tempSensor/src/bridge/extern_c_api.rs#L14'>C Extern</a> → <a title='C Interface: Lines 13-17' href='components/tsproc_tempSensor/src/tsproc_tempSensor.c#L13'>C Interface</a> → <a title='C Shared Memory Variable: Line 9' href='components/tsproc_tempSensor/src/tsproc_tempSensor.c#L9'>C var_addr</a> → <a title='Memory Map: Lines 11-15' href='microkit.system#L11'>Memory Map</a></td></tr>
    </table>
- **GUMBO**

    <table>
    <tr><th colspan=4>Integration</th></tr>
    <tr><td>guarantee currentTempOutputRange</td>
    <td><a href=../../aadl/packages/TempSensor.aadl#L49>GUMBO</a></td>
    <td><a href=crates/tsproc_tempSensor/src/bridge/tsproc_tempSensor_api.rs#L37>Verus</a></td>
    <td><a href=crates/tsproc_tempSensor/src/bridge/tsproc_tempSensor_GUMBOX.rs#L21>GUMBOX</a></td>
    </tr></table>
    <table>
    <tr><th colspan=4>Initialize</th></tr>
    <tr><td>guarantee currentTempInitialVal</td>
    <td><a href=../../aadl/packages/TempSensor.aadl#L53>GUMBO</a></td>
    <td><a href=crates/tsproc_tempSensor/src/component/tsproc_tempSensor_app.rs#L26>Verus</a></td>
    <td><a href=crates/tsproc_tempSensor/src/bridge/tsproc_tempSensor_GUMBOX.rs#L32>GUMBOX</a></td>
    </tr></table>


#### tempControl: TempControlSystem::TempControl.i

 - **Entry Points**


    Initialize: [Rust](crates/tcproc_tempControl/src/component/tcproc_tempControl_app.rs#L25)

    TimeTriggered: [Rust](crates/tcproc_tempControl/src/component/tcproc_tempControl_app.rs#L43)


- **APIs**

    <table>
    <tr><th>Port Name</th><th>Direction</th><th>Kind</th><th>Payload</th><th>Realizations</th></tr>
    <tr><td><a title='Model' href='../../aadl/packages/TempControlSystem.aadl#L142'>currentTemp</a></td>
        <td>In</td><td>Data</td>
        <td>TempSensor::Temperature.i</td><td><a title='Memory Map: Lines 29-33' href='microkit.system#L29'>Memory Map</a> → <a title='C Shared Memory Variable: Line 9' href='components/tcproc_tempControl/src/tcproc_tempControl.c#L9'>C var_addr</a> → <a title='C Interface: Lines 21-30' href='components/tcproc_tempControl/src/tcproc_tempControl.c#L21'>C Interface</a> → <a title='C Extern: Line 14' href='crates/tcproc_tempControl/src/bridge/extern_c_api.rs#L14'>C Extern</a> → <a title='Rust/C Interface: Lines 20-27' href='crates/tcproc_tempControl/src/bridge/extern_c_api.rs#L20'>Rust/C Interface</a> → <a title='Unverified Rust Interface: Lines 23-33' href='crates/tcproc_tempControl/src/bridge/tcproc_tempControl_api.rs#L23'>Unverified Rust Interface</a> → <a title='Rust/Verus API: Lines 83-95' href='crates/tcproc_tempControl/src/bridge/tcproc_tempControl_api.rs#L83'>Rust/Verus API</a></td></tr>
    <tr><td><a title='Model' href='../../aadl/packages/TempControlSystem.aadl#L144'>fanAck</a></td>
        <td>In</td><td>Data</td>
        <td>CoolingFan::FanAck</td><td><a title='Memory Map: Lines 44-48' href='microkit.system#L44'>Memory Map</a> → <a title='C Shared Memory Variable: Line 14' href='components/tcproc_tempControl/src/tcproc_tempControl.c#L14'>C var_addr</a> → <a title='C Interface: Lines 53-62' href='components/tcproc_tempControl/src/tcproc_tempControl.c#L53'>C Interface</a> → <a title='C Extern: Line 15' href='crates/tcproc_tempControl/src/bridge/extern_c_api.rs#L15'>C Extern</a> → <a title='Rust/C Interface: Lines 29-36' href='crates/tcproc_tempControl/src/bridge/extern_c_api.rs#L29'>Rust/C Interface</a> → <a title='Unverified Rust Interface: Lines 36-43' href='crates/tcproc_tempControl/src/bridge/tcproc_tempControl_api.rs#L36'>Unverified Rust Interface</a> → <a title='Rust/Verus API: Lines 96-105' href='crates/tcproc_tempControl/src/bridge/tcproc_tempControl_api.rs#L96'>Rust/Verus API</a></td></tr>
    <tr><td><a title='Model' href='../../aadl/packages/TempControlSystem.aadl#L145'>setPoint</a></td>
        <td>In</td><td>Data</td>
        <td>TempControlSystem::SetPoint.i</td><td><a title='Memory Map: Lines 39-43' href='microkit.system#L39'>Memory Map</a> → <a title='C Shared Memory Variable: Line 12' href='components/tcproc_tempControl/src/tcproc_tempControl.c#L12'>C var_addr</a> → <a title='C Interface: Lines 40-49' href='components/tcproc_tempControl/src/tcproc_tempControl.c#L40'>C Interface</a> → <a title='C Extern: Line 16' href='crates/tcproc_tempControl/src/bridge/extern_c_api.rs#L16'>C Extern</a> → <a title='Rust/C Interface: Lines 38-45' href='crates/tcproc_tempControl/src/bridge/extern_c_api.rs#L38'>Rust/C Interface</a> → <a title='Unverified Rust Interface: Lines 46-53' href='crates/tcproc_tempControl/src/bridge/tcproc_tempControl_api.rs#L46'>Unverified Rust Interface</a> → <a title='Rust/Verus API: Lines 106-115' href='crates/tcproc_tempControl/src/bridge/tcproc_tempControl_api.rs#L106'>Rust/Verus API</a></td></tr>
    <tr><td><a title='Model' href='../../aadl/packages/TempControlSystem.aadl#L147'>fanCmd</a></td>
        <td>Out</td><td>Data</td>
        <td>CoolingFan::FanCmd</td><td><a title='Rust/Verus API: Lines 68-79' href='crates/tcproc_tempControl/src/bridge/tcproc_tempControl_api.rs#L68'>Rust/Verus API</a> → <a title='Unverified Rust Interface: Lines 13-18' href='crates/tcproc_tempControl/src/bridge/tcproc_tempControl_api.rs#L13'>Unverified Rust Interface</a> → <a title='Rust/C Interface: Lines 47-52' href='crates/tcproc_tempControl/src/bridge/extern_c_api.rs#L47'>Rust/C Interface</a> → <a title='C Extern: Line 17' href='crates/tcproc_tempControl/src/bridge/extern_c_api.rs#L17'>C Extern</a> → <a title='C Interface: Lines 32-36' href='components/tcproc_tempControl/src/tcproc_tempControl.c#L32'>C Interface</a> → <a title='C Shared Memory Variable: Line 11' href='components/tcproc_tempControl/src/tcproc_tempControl.c#L11'>C var_addr</a> → <a title='Memory Map: Lines 34-38' href='microkit.system#L34'>Memory Map</a></td></tr>
    </table>
- **GUMBO**

    <table>
    <tr><th colspan=3>State Variables</th></tr>
    <tr><td>latestFanCmd</td>
    <td><a href=../../aadl/packages/TempControlSystem.aadl#L165>GUMBO</a></td>
    <td><a href=crates/tcproc_tempControl/src/component/tcproc_tempControl_app.rs#L11>Verus</a></td></tr></table>
    <table>
    <tr><th colspan=4>Integration</th></tr>
    <tr><td>assume currentTempInputRange</td>
    <td><a href=../../aadl/packages/TempControlSystem.aadl#L168>GUMBO</a></td>
    <td><a href=crates/tcproc_tempControl/src/bridge/tcproc_tempControl_api.rs#L90>Verus</a></td>
    <td><a href=crates/tcproc_tempControl/src/bridge/tcproc_tempControl_GUMBOX.rs#L21>GUMBOX</a></td>
    </tr></table>
    <table>
    <tr><th colspan=4>Initialize</th></tr>
    <tr><td>guarantee initLatestFanCmd</td>
    <td><a href=../../aadl/packages/TempControlSystem.aadl#L173>GUMBO</a></td>
    <td><a href=crates/tcproc_tempControl/src/component/tcproc_tempControl_app.rs#L30>Verus</a></td>
    <td><a href=crates/tcproc_tempControl/src/bridge/tcproc_tempControl_GUMBOX.rs#L33>GUMBOX</a></td>
    </tr>
    <tr><td>guarantee initFanCmd</td>
    <td><a href=../../aadl/packages/TempControlSystem.aadl#L176>GUMBO</a></td>
    <td><a href=crates/tcproc_tempControl/src/component/tcproc_tempControl_app.rs#L33>Verus</a></td>
    <td><a href=crates/tcproc_tempControl/src/bridge/tcproc_tempControl_GUMBOX.rs#L44>GUMBOX</a></td>
    </tr></table>
    <table>
    <tr><th colspan=4>Compute</th></tr>
    <tr><td>assume validSetPoint</td>
    <td><a href=../../aadl/packages/TempControlSystem.aadl#L182>GUMBO</a></td>
    <td><a href=crates/tcproc_tempControl/src/component/tcproc_tempControl_app.rs#L48>Verus</a></td>
    <td><a href=crates/tcproc_tempControl/src/bridge/tcproc_tempControl_GUMBOX.rs#L80>GUMBOX</a></td>
    </tr>
    <tr><td>guarantee altCurrentTempLTSetPoint</td>
    <td><a href=../../aadl/packages/TempControlSystem.aadl#L185>GUMBO</a></td>
    <td><a href=crates/tcproc_tempControl/src/component/tcproc_tempControl_app.rs#L54>Verus</a></td>
    <td><a href=crates/tcproc_tempControl/src/bridge/tcproc_tempControl_GUMBOX.rs#L128>GUMBOX</a></td>
    </tr>
    <tr><td>guarantee altCurrentTempGTSetPoint</td>
    <td><a href=../../aadl/packages/TempControlSystem.aadl#L190>GUMBO</a></td>
    <td><a href=crates/tcproc_tempControl/src/component/tcproc_tempControl_app.rs#L60>Verus</a></td>
    <td><a href=crates/tcproc_tempControl/src/bridge/tcproc_tempControl_GUMBOX.rs#L150>GUMBOX</a></td>
    </tr>
    <tr><td>guarantee altCurrentTempInRange</td>
    <td><a href=../../aadl/packages/TempControlSystem.aadl#L195>GUMBO</a></td>
    <td><a href=crates/tcproc_tempControl/src/component/tcproc_tempControl_app.rs#L66>Verus</a></td>
    <td><a href=crates/tcproc_tempControl/src/bridge/tcproc_tempControl_GUMBOX.rs#L174>GUMBOX</a></td>
    </tr></table>


#### operatorInterface: TempControlSystem::OperatorInterface.i

 - **Entry Points**


    Initialize: [Rust](crates/oiproc_operatorInterface/src/component/oiproc_operatorInterface_app.rs#L21)

    TimeTriggered: [Rust](crates/oiproc_operatorInterface/src/component/oiproc_operatorInterface_app.rs#L30)


- **APIs**

    <table>
    <tr><th>Port Name</th><th>Direction</th><th>Kind</th><th>Payload</th><th>Realizations</th></tr>
    <tr><td><a title='Model' href='../../aadl/packages/TempControlSystem.aadl#L272'>currentTemp</a></td>
        <td>In</td><td>Data</td>
        <td>TempSensor::Temperature.i</td><td><a title='Memory Map: Lines 62-66' href='microkit.system#L62'>Memory Map</a> → <a title='C Shared Memory Variable: Line 9' href='components/oiproc_operatorInterface/src/oiproc_operatorInterface.c#L9'>C var_addr</a> → <a title='C Interface: Lines 17-26' href='components/oiproc_operatorInterface/src/oiproc_operatorInterface.c#L17'>C Interface</a> → <a title='C Extern: Line 14' href='crates/oiproc_operatorInterface/src/bridge/extern_c_api.rs#L14'>C Extern</a> → <a title='Rust/C Interface: Lines 18-25' href='crates/oiproc_operatorInterface/src/bridge/extern_c_api.rs#L18'>Rust/C Interface</a> → <a title='Unverified Rust Interface: Lines 23-30' href='crates/oiproc_operatorInterface/src/bridge/oiproc_operatorInterface_api.rs#L23'>Unverified Rust Interface</a> → <a title='Rust/Verus API: Lines 56-63' href='crates/oiproc_operatorInterface/src/bridge/oiproc_operatorInterface_api.rs#L56'>Rust/Verus API</a></td></tr>
    <tr><td><a title='Model' href='../../aadl/packages/TempControlSystem.aadl#L274'>setPoint</a></td>
        <td>Out</td><td>Data</td>
        <td>TempControlSystem::SetPoint.i</td><td><a title='Rust/Verus API: Lines 43-52' href='crates/oiproc_operatorInterface/src/bridge/oiproc_operatorInterface_api.rs#L43'>Rust/Verus API</a> → <a title='Unverified Rust Interface: Lines 13-18' href='crates/oiproc_operatorInterface/src/bridge/oiproc_operatorInterface_api.rs#L13'>Unverified Rust Interface</a> → <a title='Rust/C Interface: Lines 27-32' href='crates/oiproc_operatorInterface/src/bridge/extern_c_api.rs#L27'>Rust/C Interface</a> → <a title='C Extern: Line 15' href='crates/oiproc_operatorInterface/src/bridge/extern_c_api.rs#L15'>C Extern</a> → <a title='C Interface: Lines 28-32' href='components/oiproc_operatorInterface/src/oiproc_operatorInterface.c#L28'>C Interface</a> → <a title='C Shared Memory Variable: Line 11' href='components/oiproc_operatorInterface/src/oiproc_operatorInterface.c#L11'>C var_addr</a> → <a title='Memory Map: Lines 67-71' href='microkit.system#L67'>Memory Map</a></td></tr>
    </table>


#### fan: CoolingFan::Fan.i

 - **Entry Points**


    Initialize: [Rust](crates/fanproc_fan/src/component/fanproc_fan_app.rs#L21)

    TimeTriggered: [Rust](crates/fanproc_fan/src/component/fanproc_fan_app.rs#L30)


- **APIs**

    <table>
    <tr><th>Port Name</th><th>Direction</th><th>Kind</th><th>Payload</th><th>Realizations</th></tr>
    <tr><td><a title='Model' href='../../aadl/packages/CoolingFan.aadl#L35'>fanCmd</a></td>
        <td>In</td><td>Data</td>
        <td>CoolingFan::FanCmd</td><td><a title='Memory Map: Lines 85-89' href='microkit.system#L85'>Memory Map</a> → <a title='C Shared Memory Variable: Line 9' href='components/fanproc_fan/src/fanproc_fan.c#L9'>C var_addr</a> → <a title='C Interface: Lines 17-26' href='components/fanproc_fan/src/fanproc_fan.c#L17'>C Interface</a> → <a title='C Extern: Line 14' href='crates/fanproc_fan/src/bridge/extern_c_api.rs#L14'>C Extern</a> → <a title='Rust/C Interface: Lines 18-25' href='crates/fanproc_fan/src/bridge/extern_c_api.rs#L18'>Rust/C Interface</a> → <a title='Unverified Rust Interface: Lines 23-30' href='crates/fanproc_fan/src/bridge/fanproc_fan_api.rs#L23'>Unverified Rust Interface</a> → <a title='Rust/Verus API: Lines 56-63' href='crates/fanproc_fan/src/bridge/fanproc_fan_api.rs#L56'>Rust/Verus API</a></td></tr>
    <tr><td><a title='Model' href='../../aadl/packages/CoolingFan.aadl#L37'>fanAck</a></td>
        <td>Out</td><td>Data</td>
        <td>CoolingFan::FanAck</td><td><a title='Rust/Verus API: Lines 43-52' href='crates/fanproc_fan/src/bridge/fanproc_fan_api.rs#L43'>Rust/Verus API</a> → <a title='Unverified Rust Interface: Lines 13-18' href='crates/fanproc_fan/src/bridge/fanproc_fan_api.rs#L13'>Unverified Rust Interface</a> → <a title='Rust/C Interface: Lines 27-32' href='crates/fanproc_fan/src/bridge/extern_c_api.rs#L27'>Rust/C Interface</a> → <a title='C Extern: Line 15' href='crates/fanproc_fan/src/bridge/extern_c_api.rs#L15'>C Extern</a> → <a title='C Interface: Lines 28-32' href='components/fanproc_fan/src/fanproc_fan.c#L28'>C Interface</a> → <a title='C Shared Memory Variable: Line 11' href='components/fanproc_fan/src/fanproc_fan.c#L11'>C var_addr</a> → <a title='Memory Map: Lines 90-94' href='microkit.system#L90'>Memory Map</a></td></tr>
    </table>

