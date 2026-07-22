// #Sireum

package tc.TempControlSoftwareSystem

import org.sireum._
import tc._

// This file will not be overwritten so is safe to edit
object OperatorInterfacePeriodic_p_tcproc_operatorInterface {

  def initialise(api: OperatorInterfacePeriodic_p_Initialization_Api): Unit = {
    // example api usage

    api.logInfo("Example info logging")
    api.logDebug("Example debug logging")
    api.logError("Example error logging")

    api.put_setPoint(TempControlSoftwareSystem.SetPoint_i.example())
  }

  def timeTriggered(api: OperatorInterfacePeriodic_p_Operational_Api): Unit = {
    // example api usage

    val apiUsage_currentTemp: Option[TempSensor.Temperature_i] = api.get_currentTemp()
    api.logInfo(s"Received on data port currentTemp: ${apiUsage_currentTemp}")
  }

  def finalise(api: OperatorInterfacePeriodic_p_Operational_Api): Unit = { }
}
