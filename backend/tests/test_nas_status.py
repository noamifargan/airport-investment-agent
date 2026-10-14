from airport_agent.data.sources.nas_status import parse

SAMPLE = b"""<AIRPORT_STATUS_INFORMATION><Update_Time>Wed Oct 14 12:11:47 2026 GMT</Update_Time>
<Delay_type><Name>Ground Delay Programs</Name><Ground_Delay_List><Ground_Delay><ARPT>SFO</ARPT>
<Reason>low ceilings</Reason><Avg>1 hour and 6 minutes</Avg><Max>2 hours and 47 minutes</Max></Ground_Delay></Ground_Delay_List></Delay_type>
<Delay_type><Name>Ground Stops</Name><Ground_Stop_List><Program><ARPT>EWR</ARPT><Reason>thunderstorms</Reason>
<End_Time>3:30 pm EDT</End_Time></Program></Ground_Stop_List></Delay_type>
<Delay_type><Name>General Arrival/Departure Delay Info</Name><Arrival_Departure_Delay_List><Delay><ARPT>TEB</ARPT>
<Reason>RWY:Maintenance</Reason><Arrival_Departure Type="Departure"><Min>31 minutes</Min><Max>45 minutes</Max>
<Trend>Increasing</Trend></Arrival_Departure></Delay></Arrival_Departure_Delay_List></Delay_type>
<Delay_type><Name>Airport Closures</Name><Airport_Closure_List><Airport><ARPT>SNA</ARPT><Reason>!SNA AD AP CLSD</Reason>
<Start>Oct 13 at 06:30 UTC.</Start><Reopen>Oct 17 at 13:15 UTC.</Reopen></Airport></Airport_Closure_List></Delay_type>
</AIRPORT_STATUS_INFORMATION>"""


def test_parse_all_event_types():
    updated, events = parse(SAMPLE)
    assert updated.startswith("Wed Oct 14")
    by_airport = {e["airport"]: e for e in events}
    assert by_airport["SFO"]["type"] == "Ground Delay Program" and "avg 1 hour" in by_airport["SFO"]["detail"]
    assert by_airport["EWR"]["type"] == "Ground Stop"
    assert by_airport["TEB"]["detail"].startswith("departure delays 31 minutes")
    assert by_airport["SNA"]["type"] == "Closure/restriction NOTAM"
