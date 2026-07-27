// #Sireum

package tc.TempSensor

import org.sireum._
import tc._

// This file will not be overwritten if HAMR codegen is rerun
object TempSensor_i_tcproc_tempSensor {

  def initialise(api: TempSensor_i_Initialization_Api): Unit = {
    Contract(
      Ensures(
        // BEGIN INITIALIZES ENSURES
        // guarantee currentTempInitialVal
        api.currentTemp.degrees == 72.0f
        // END INITIALIZES ENSURES
      )
    )
    // example api usage

    api.logInfo("Example info logging")
    api.logDebug("Example debug logging")
    api.logError("Example error logging")

    api.put_currentTemp(TempSensor.Temperature_i(degrees = 72.0f, unit = TempSensor.TempUnit.Fahrenheit))
  }

  def timeTriggered(api: TempSensor_i_Operational_Api): Unit = {
    // example api usage


  }

  def finalise(api: TempSensor_i_Operational_Api): Unit = { }
}
