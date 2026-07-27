// #Sireum

package tc.TempControlSystem

import org.sireum._
import tc._

// This file will not be overwritten if HAMR codegen is rerun
object TempControl_i_tcproc_tempControl {

  // BEGIN STATE VARS
  var latestFanCmd: CoolingFan.FanCmd.Type = CoolingFan.FanCmd.On
  // END STATE VARS

  def initialise(api: TempControl_i_Initialization_Api): Unit = {
    Contract(
      Modifies(
        api,
        // BEGIN INITIALIZES MODIFIES
        latestFanCmd
        // END INITIALIZES MODIFIES
      ),
      Ensures(
        // BEGIN INITIALIZES ENSURES
        // guarantee initLatestFanCmd
        //   Initialize state variable
        latestFanCmd == CoolingFan.FanCmd.Off,
        // guarantee initFanCmd
        //   Initial fan command
        api.fanCmd == CoolingFan.FanCmd.Off
        // END INITIALIZES ENSURES
      )
    )
    latestFanCmd = CoolingFan.FanCmd.Off
    api.put_fanCmd(CoolingFan.FanCmd.Off)
  }

  def timeTriggered(api: TempControl_i_Operational_Api): Unit = {
    Contract(
      Modifies(
        api,
        // BEGIN COMPUTE MODIFIES timeTriggered
        latestFanCmd
        // END COMPUTE MODIFIES timeTriggered
      ),
      Ensures(
        // BEGIN COMPUTE ENSURES timeTriggered
        // guarantee altCurrentTempLTSetPoint
        //   If current temperature is less than
        //   the current low set point, then the fan state shall be Off
        api.currentTemp.degrees < api.setPoint.low.degrees __>:
          latestFanCmd == CoolingFan.FanCmd.Off &&
            api.fanCmd == CoolingFan.FanCmd.Off,
        // guarantee altCurrentTempGTSetPoint
        //   If current temperature is greater than
        //   the current high set point, then the fan state shall be On
        api.currentTemp.degrees > api.setPoint.high.degrees __>:
          latestFanCmd == CoolingFan.FanCmd.On &
            api.fanCmd == CoolingFan.FanCmd.On,
        // guarantee altCurrentTempInRange
        //   If current temperature is greater than or equal to the 
        //   current low set point and less than or equal to the current high set point, 
        //   then the current fan state is maintained.
        api.currentTemp.degrees >= api.setPoint.low.degrees &
          api.currentTemp.degrees <= api.setPoint.high.degrees ___>:
          latestFanCmd == In(latestFanCmd) &
            api.fanCmd == latestFanCmd
        // END COMPUTE ENSURES timeTriggered
      )
    )
    val currentTemp: TempSensor.Temperature_i = api.get_currentTemp().get
    val setPoint: TempControlSystem.SetPoint_i = api.get_setPoint().get

    val newCmd: CoolingFan.FanCmd.Type =
      if (currentTemp.degrees < setPoint.low.degrees) CoolingFan.FanCmd.Off
      else if (currentTemp.degrees > setPoint.high.degrees) CoolingFan.FanCmd.On
      else latestFanCmd // temperature in range — maintain current fan state

    latestFanCmd = newCmd
    api.put_fanCmd(newCmd)
  }

  def finalise(api: TempControl_i_Operational_Api): Unit = { }
}
