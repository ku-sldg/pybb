// #Sireum

package tc.TempSensor

import org.sireum._
import tc._

// This file will not be overwritten so is safe to edit
object TempSensorPeriodic_p_tcproc_tempSensor {

  def initialise(api: TempSensorPeriodic_p_Initialization_Api): Unit = {
    Contract(
      Ensures(
        // BEGIN INITIALIZES ENSURES
        // guarantee initializes
        api.currentTemp.degrees == 72.0f
        // END INITIALIZES ENSURES
      )
    )
    // example api usage

    api.logInfo("Example info logging")
    api.logDebug("Example debug logging")
    api.logError("Example error logging")

    api.put_currentTemp(TempSensor.Temperature_i(degrees = 72.0f))
  }

  def timeTriggered(api: TempSensorPeriodic_p_Operational_Api): Unit = {
    // example api usage


  }

  def finalise(api: TempSensorPeriodic_p_Operational_Api): Unit = { }
}
