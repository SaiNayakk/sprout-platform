#!/data/data/com.termux/files/usr/bin/sh
# The phone's sizes, read by every host's run.sh and by Postgres's:   . "$HOME/sprout/profile.sh" HOST
#   SPROUT_PROFILE=peak  (the default) the sizes the capacity runs were measured at: the README's numbers
#   SPROUT_PROFILE=demo  the same services and cells, sized for a handful of visitors so the phone keeps room
# Switch with `sh ~/sprout/ctl.sh profile demo|peak`, which writes SPROUT_PROFILE to ~/.sprout.env and restarts Sprout.
# Every Spring setting here is an environment variable, so it applies to every service in the host at once.
# Sets SPROUT_JAVA_OPTS (a host's own SPROUT_<HOST>_JAVA_OPTS in ~/.sprout.env still wins) and SPROUT_PG_OPTS.

case "${SPROUT_PROFILE:-peak}" in
  demo)
    # each service in a host has its own Tomcat, and an idle Tomcat keeps ten threads: the money host had 70
    export SERVER_TOMCAT_THREADS_MINSPARE=1 SERVER_TOMCAT_THREADS_MAX=8
    # two connections each: a request can hold one while a housekeeper uses the other. (Closing idle ones saves
    # nothing: every service's housekeepers use theirs every few seconds, so none is ever idle for long.)
    export SPRING_DATASOURCE_HIKARI_MAXIMUMPOOLSIZE=2 SPRING_DATASOURCE_HIKARI_MINIMUMIDLE=1
    # live heap measured at 35-77 MB on 2026-10-29. The serial collector grows the heap to its limit and keeps it:
    # these ratios hand back what a collection frees, so an idle host sits near its live data
    SPROUT_JAVA_OPTS="-XX:+UseSerialGC -Xms16m -Xmx96m -XX:MinHeapFreeRatio=10 -XX:MaxHeapFreeRatio=25 -Xss512k -XX:MaxMetaspaceSize=128m -XX:ReservedCodeCacheSize=24m -XX:TieredStopAtLevel=1 -XX:CICompilerCount=1"
    SPROUT_PG_OPTS="-c shared_buffers=32MB -c work_mem=2MB -c maintenance_work_mem=16MB"
    ;;
  *)
    SPROUT_JAVA_OPTS="-XX:+UseSerialGC -Xms32m -Xmx160m -Xss512k -XX:MaxMetaspaceSize=192m \
-XX:ReservedCodeCacheSize=48m -XX:TieredStopAtLevel=1"
    SPROUT_PG_OPTS=""
    ;;
esac
