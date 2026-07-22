package tc.TempControlSoftwareSystem

import org.sireum._
import tc._
import tc.TempControlSoftwareSystem._

// This file will not be overwritten so is safe to edit
class TempControlPeriodic_p_tcproc_tempControl_Test extends TempControlPeriodic_p_tcproc_tempControl_ScalaTest {

  // Shared setPoint: low=60°F, high=80°F
  val setPoint = TempControlSoftwareSystem.SetPoint_i(
    low  = TempSensor.Temperature_i(degrees = 60.0f),
    high = TempSensor.Temperature_i(degrees = 80.0f)
  )

  test("Fan should be OFF when temp is below low setpoint (too cold)") {
    put_concrete_inputs(
      currentTemp = TempSensor.Temperature_i(degrees = 50.0f), // below low=60
      fanAck      = CoolingFan.FanAck.Ok,
      setPoint    = setPoint
    )
    testCompute()
    check_concrete_output(fanCmd = cmd => {
      println(s"  temp=50 < low=60  →  fanCmd=$cmd  (expected: Off)")
      cmd == CoolingFan.FanCmd.Off
    })
  }

  test("Fan should be ON when temp is above high setpoint (too hot)") {
    put_concrete_inputs(
      currentTemp = TempSensor.Temperature_i(degrees = 90.0f), // above high=80
      fanAck      = CoolingFan.FanAck.Ok,
      setPoint    = setPoint
    )
    testCompute()
    check_concrete_output(fanCmd = cmd => {
      println(s"  temp=90 > high=80  →  fanCmd=$cmd  (expected: On)")
      cmd == CoolingFan.FanCmd.On
    })
  }

  test("Fan should MAINTAIN state when temp equals low setpoint (boundary)") {
    // First drive fan On so latestFanCmd = On
    put_concrete_inputs(
      currentTemp = TempSensor.Temperature_i(degrees = 90.0f),
      fanAck      = CoolingFan.FanAck.Ok,
      setPoint    = setPoint
    )
    testCompute()

    // Now temp = exactly low setpoint (60°F)
    // Contract says: temp >= low AND temp <= high → maintain state (fan stays On)
    // Bug 2 turns fan Off because it uses <= instead of <
    put_concrete_inputs(
      currentTemp = TempSensor.Temperature_i(degrees = 60.0f), // exactly at low boundary
      fanAck      = CoolingFan.FanAck.Ok,
      setPoint    = setPoint
    )
    testCompute()
    check_concrete_output(fanCmd = cmd => {
      println(s"  temp=60 == low=60  →  fanCmd=$cmd  (expected: On — maintain, not Off)")
      cmd == CoolingFan.FanCmd.On
    })
  }

  test("Fan should MAINTAIN state when temp is in range") {
    // First call: drive fan On (temp too hot)
    put_concrete_inputs(
      currentTemp = TempSensor.Temperature_i(degrees = 90.0f),
      fanAck      = CoolingFan.FanAck.Ok,
      setPoint    = setPoint
    )
    testCompute()

    // Second call: temp drops to in-range — fan should stay On
    put_concrete_inputs(
      currentTemp = TempSensor.Temperature_i(degrees = 70.0f), // in range
      fanAck      = CoolingFan.FanAck.Ok,
      setPoint    = setPoint
    )
    testCompute()
    check_concrete_output(fanCmd = cmd => {
      println(s"  temp=70 in [60,80]  →  fanCmd=$cmd  (expected: On — maintain)")
      cmd == CoolingFan.FanCmd.On
    })
  }
}
