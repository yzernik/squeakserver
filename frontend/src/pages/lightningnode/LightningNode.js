import React, { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import {useHistory} from "react-router-dom";
import {
  Grid,
  Button,
  AppBar,
  Tabs,
  Tab,
  Box,
} from "@material-ui/core";
import { useTheme } from "@material-ui/styles";
import {
  ResponsiveContainer,
  ComposedChart,
  AreaChart,
  LineChart,
  Line,
  Area,
  PieChart,
  Pie,
  Cell,
  YAxis,
  XAxis,
} from "recharts";

// styles
import useStyles from "./styles";

// components
import PageTitle from "../../components/PageTitle";
import Widget from "../../components/Widget";
import { Typography } from "../../components/Wrappers";
import OpenChannelDialog from "../../components/OpenChannelDialog";
import ChannelItem from "../../components/ChannelItem";
import PendingOpenChannelItem from "../../components/PendingOpenChannelItem";

import {
  lndGetInfo,
  lndWalletBalance,
  lndGetTransactions,
  lndListPeersRequest,
  lndListChannelsRequest,
  lndPendingChannelsRequest,
  lndConnectPeerRequest,
  lndDisconnectPeerRequest,
} from "../../squeakclient/requests"
import {
  reloadRoute,
} from "../../navigation/navigation"


export default function LightningNodePage() {
  var classes = useStyles();
  var theme = useTheme();

  const history = useHistory();
  const { pubkey, host, port } = useParams();
  const [value, setValue] = useState(0);
  const [peers, setPeers] = useState(null);
  const [channels, setChannels] = useState(null);
  const [pendingChannels, setPendingChannels] = useState(null);
  const [openChannelDialogOpen, setOpenChannelDialogOpen] = useState(false);

  function a11yProps(index) {
    return {
      id: `simple-tab-${index}`,
      'aria-controls': `simple-tabpanel-${index}`,
    };
  }

  const handleChange = (event, newValue) => {
    setValue(newValue);
  };

  const handleClickConnectPeer = () => {
    var lightningHost = host + ":" + port;
    connectPeer(pubkey, lightningHost);
  };

  const handleClickOpenChannel = () => {
    console.log("Handle click open channel.");
    setOpenChannelDialogOpen(true);
  };

  const handleCloseOpenChannelDialog = () => {
    setOpenChannelDialogOpen(false);
  };

  const handleClickDisconnectPeer = () => {
    disconnectPeer(pubkey);
  };

  const isConnected = () => {
    if (peers == null) {
      return false;
    }
    var i;
    for (i = 0; i < peers.length; i++) {
      if (pubkey == peers[i].getPubKey()) {
        return true;
      }
    }
    return false;
  };

  const hasChannelToPeer = () => {
    if (channels == null) {
      return false;
    }
    var i;
    for (i = 0; i < channels.length; i++) {
      if (pubkey == channels[i].getRemotePubkey()) {
        return true;
      }
    }
    return false;
  };

  const listPeers = () => {
    lndListPeersRequest(setPeers);
  };
  const listChannels = () => {
    lndListChannelsRequest(setChannels);
  };
  const getPendingChannels = () => {
    lndPendingChannelsRequest(setPendingChannels);
  };
  const connectPeer = (pubkey, host) => {
    lndConnectPeerRequest(pubkey, host, () => {
      reloadRoute(history);
    });
  };
  const disconnectPeer = (pubkey) => {
    lndDisconnectPeerRequest(pubkey, () => {
      reloadRoute(history);
    });
  };

  useEffect(()=>{
    listPeers()
  },[]);
  useEffect(()=>{
    listChannels()
  },[]);
  useEffect(()=>{
    getPendingChannels()
  },[]);

  function ConnectPeerButton() {
    return (
      <>
      <Grid item xs={12}>
        <div className={classes.root}>
          <Button
            variant="contained"
            onClick={() => {
              handleClickConnectPeer();
            }}>Connect Peer
          </Button>
        </div>
      </Grid>
      </>
    )
  }

  function DisconnectPeerButton() {
    return (
      <>
      <Grid item xs={12}>
        <div className={classes.root}>
          <Button
            variant="contained"
            onClick={() => {
              handleClickDisconnectPeer();
            }}>Disconnect Peer
          </Button>
        </div>
      </Grid>
      </>
    )
  }

  function OpenChannelButton() {
    return (
      <>
      <Grid item xs={12}>
        <div className={classes.root}>
          <Button
            variant="contained"
            onClick={() => {
              handleClickOpenChannel();
            }}>Open Channel
          </Button>
        </div>
      </Grid>
      </>
    )
  }

  function NodeInfoGridItem() {
    return (
      <Grid item xs={12}>
      <Widget disableWidgetMenu>
      <Grid
        container
        direction="row"
        justify="flex-start"
        alignItems="center"
      >
        <Grid item>
          <Typography color="text" colorBrightness="secondary">
            pubkey
          </Typography>
          <Typography size="md">{pubkey}</Typography>
        </Grid>
      </Grid>

      <Grid
        container
        direction="row"
        justify="flex-start"
        alignItems="center"
      >
        <Grid item>
          <Typography color="text" colorBrightness="secondary">
            host
          </Typography>
          <Typography size="md">{host}</Typography>
        </Grid>
      </Grid>

      <Grid
        container
        direction="row"
        justify="flex-start"
        alignItems="center"
      >
        <Grid item>
          <Typography color="text" colorBrightness="secondary">
            port
          </Typography>
          <Typography size="md">{port}</Typography>
        </Grid>
      </Grid>

      <Grid
        container
        direction="row"
        justify="flex-start"
        alignItems="center"
      >
        <Grid item>
          <Typography color="text" colorBrightness="secondary">
            connected
          </Typography>
          <Typography size="md">
          {IsConnected()}
          </Typography>
          {isConnected()
            ? DisconnectPeerButton()
            : ConnectPeerButton()
          }
        </Grid>
      </Grid>

      <Grid
        container
        direction="row"
        justify="flex-start"
        alignItems="center"
      >
        <Grid item>
          <Typography color="text" colorBrightness="secondary">
            channel to peer
          </Typography>
          <Typography size="md">
          {HasChannelToPeer()}
          </Typography>
          {!hasChannelToPeer() &&
            OpenChannelButton()
          }
        </Grid>
      </Grid>

       </Widget>
      </Grid>
    )
  }

  function ChannelsGridItem() {
    var nodeChannels = channels.filter(channel => channel.getRemotePubkey() == pubkey);
    var nodePendingOpenChannels = pendingChannels.getPendingOpenChannelsList().filter(pendingOpenChannel => pendingOpenChannel.getChannel().getRemoteNodePub() == pubkey);
    return (
      <Grid item xs={12}>
      <Widget disableWidgetMenu>
      <Grid
        container
        direction="row"
        justify="flex-start"
        alignItems="center"
      >
        <Grid item xs={12}>
        {nodePendingOpenChannels.map(pendingOpenChannel =>
          <Box
            p={1}
            key={pendingOpenChannel.getChannel().getChannelPoint()}
            >
          <PendingOpenChannelItem
            key={pendingOpenChannel.getChannel().getChannelPoint()}
            pendingOpenChannel={pendingOpenChannel}>
          </PendingOpenChannelItem>
          </Box>
        )}
        {nodeChannels.map(channel =>
          <Box
            p={1}
            key={channel.getChannelPoint()}
            >
          <ChannelItem
            key={channel.getChannelPoint()}
            channel={channel}>
          </ChannelItem>
          </Box>
        )}
        </Grid>
      </Grid>
      </Widget>
      </Grid>
    )
  }

  function IsConnected() {
    return (
      isConnected().toString()
    )
  }

  function HasChannelToPeer() {
    return (
      hasChannelToPeer().toString()
    )
  }

  function NoPubkeyContent() {
    return (
      <div>
        No pubkey.
      </div>
    )
  }

  function PubkeyContent() {
    return (
      <>
        <Grid container spacing={4}>
          {NodeInfoGridItem()}
        </Grid>
      </>
    )
  }

  function ChannelsContent() {
    if (channels == null || pendingChannels == null) {
      return (
        <>
          <Grid container spacing={4}>
          <Grid item xs={12}>
          <Widget disableWidgetMenu>
          <Grid
            container
            direction="row"
            justify="flex-start"
            alignItems="center"
          >
            <Grid item xs={12}>
              Unable to load channels
            </Grid>
          </Grid>
          </Widget>
          </Grid>
          </Grid>
        </>
      )
    }

    return (
      <>
        <Grid container spacing={4}>
          {ChannelsGridItem()}
        </Grid>
      </>
    )
  }

  function TabPanel(props) {
    const { children, value, index, ...other } = props;

    return (
      <div
        role="tabpanel"
        hidden={value !== index}
        id={`simple-tabpanel-${index}`}
        aria-labelledby={`simple-tab-${index}`}
        {...other}
      >
        {value === index && (
          <div>{children}</div>
        )}
      </div>
    );
  }

  function LightningNodeTabs() {
    return (
      <>
      <AppBar position="static" color="default">
        <Tabs value={value} onChange={handleChange} aria-label="simple tabs example">
          <Tab label="Node Info" {...a11yProps(0)} />
          <Tab label="Channels" {...a11yProps(1)} />
          <Tab label="Routes" {...a11yProps(2)} />
        </Tabs>
      </AppBar>
      <TabPanel value={value} index={0}>
        {PubkeyContent()}
      </TabPanel>
      <TabPanel value={value} index={1}>
        {ChannelsContent()}
      </TabPanel>
      <TabPanel value={value} index={2}>
        Show routes here
      </TabPanel>
      </>
    )
  }

  function OpenChannelDialogContent() {
    return (
      <>
        <OpenChannelDialog
          open={openChannelDialogOpen}
          pubkey={pubkey}
          handleClose={handleCloseOpenChannelDialog}
          ></OpenChannelDialog>
      </>
    )
  }

  return (
    <>
      <PageTitle title={'Lightning Node: ' + pubkey} />
      {pubkey
        ? LightningNodeTabs()
        : NoPubkeyContent()
      }
      {OpenChannelDialogContent()}
    </>
  );
}
