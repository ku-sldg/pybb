// #Sireum

package tc.CoolingFan

import org.sireum._
import tc._

// This file will not be overwritten so is safe to edit
object FanPeriodic_p_tcproc_fan {

  def initialise(api: FanPeriodic_p_Initialization_Api): Unit = {
    // example api usage

    api.logInfo("Example info logging")
    api.logDebug("Example debug logging")
    api.logError("Example error logging")

    api.put_fanAck(CoolingFan.FanAck.Ok)
  }

  def timeTriggered(api: FanPeriodic_p_Operational_Api): Unit = {
    // example api usage

    val apiUsage_fanCmd: Option[CoolingFan.FanCmd.Type] = api.get_fanCmd()
    api.logInfo(s"Received on data port fanCmd: ${apiUsage_fanCmd}")
  }

  def finalise(api: FanPeriodic_p_Operational_Api): Unit = { }
}
