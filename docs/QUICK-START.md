# ⚡ Quick Start Guide - Network CI/CD Pipeline

Get your network testing pipeline up and running in 15 minutes!

## 🎯 What You'll Achieve

After following this guide, you'll have:
- ✅ Automated VLAN change testing
- ✅ Pre/post network state validation  
- ✅ Comprehensive reporting
- ✅ Automatic rollback on failures
- ✅ GitHub Actions integration

## 🚀 5-Minute Setup

### Step 1: Configure Your Lab Devices

Update `inventory/devices.yml` with your actual device IPs:

```yaml
devices:
  core1:
    host: 192.168.1.197    # 👈 Change to your core switch IP
    device_type: cisco_ios
  edge1:
    host: 192.168.1.198    # 👈 Change to your edge switch 1 IP  
    device_type: cisco_ios
  edge2:
    host: 192.168.1.199    # 👈 Change to your edge switch 2 IP
    device_type: cisco_ios
```

### Step 2: Set Test Target

Update `inventory/targets.yml`:

```yaml
target:
  device: edge1                    # 👈 Device to test
  interface: GigabitEthernet0/1   # 👈 Safe interface to test
test_vlan: 20                     # 👈 Safe VLAN ID
```

### Step 3: Add GitHub Secrets

In GitHub: **Settings > Secrets and variables > Actions**

Add these secrets:
- `NETWORK_USERNAME` → Your SSH username
- `NETWORK_PASSWORD` → Your SSH password  
- `FALLBACK_USER1` → Backup username (optional)
- `FALLBACK_PASS1` → Backup password (optional)

## 🧪 Test Your Setup

### Option 1: Quick Local Test

```bash
# Test connectivity to all devices
python tests/test_vlan_e2e.py --validate-only

# If that works, run a full test
python tests/test_vlan_e2e.py
```

### Option 2: GitHub Actions Test

1. Go to **Actions** tab in GitHub
2. Click **Network VLAN Change CI/CD Pipeline** 
3. Click **Run workflow**
4. Use these safe defaults:
   - Target Device: `edge1`
   - Target Interface: `GigabitEthernet0/1`
   - Target VLAN: `20`
   - Skip Rollback: `false`
   - Environment: `lab`

## 📊 Understanding Your First Test

### What Happens During the Test

```
🔍 Environment Validation
   ├── Tests SSH connectivity to all devices
   ├── Validates credentials work
   └── Confirms test targets exist

📋 Pre-Change Network Audit  
   ├── Captures current port configurations
   ├── Documents VLAN assignments
   └── Records baseline state

🔧 Execute VLAN Change Test
   ├── Changes target interface to test VLAN
   ├── Verifies change was applied
   └── Records any issues

🔍 Post-Change Validation
   ├── Re-audits all devices  
   ├── Compares before/after states
   └── Checks for side effects

🔄 Automatic Rollback
   ├── Restores original VLAN
   └── Confirms rollback successful

📄 Generate Reports
   └── Creates comprehensive documentation
```

### Success Indicators

✅ **Green checkmarks** in GitHub Actions  
✅ **"✅ PASSED"** in test reports  
✅ **No unexpected changes** detected  
✅ **Rollback completed** successfully  

## 🎓 What You've Learned

Understanding the CI/CD flow helps you see **why each step matters**:

### 1. **Pre-Change Audit** 
**Why**: Captures the "before" state so we can detect any unintended changes
**Learning**: Always document current state before making changes

### 2. **Controlled Testing**
**Why**: Tests changes in isolation with known parameters
**Learning**: Systematic testing reduces surprises in production

### 3. **Side-Effect Detection**
**Why**: Ensures your change didn't accidentally affect other ports
**Learning**: Network changes can have unexpected impacts

### 4. **Automatic Rollback**
**Why**: Provides safety net if something goes wrong
**Learning**: Always have a back-out plan

### 5. **Comprehensive Reporting**  
**Why**: Documents what happened for troubleshooting and compliance
**Learning**: Good documentation is crucial for network management

## 🔧 Common Customizations

### Change Test Interface

```yaml
# In inventory/targets.yml
target:
  device: edge2                    # Different device
  interface: GigabitEthernet0/5   # Different interface
test_vlan: 30                     # Different VLAN
```

### Add More Devices

```yaml
# In inventory/devices.yml  
devices:
  core1:
    host: 192.168.1.197
    device_type: cisco_ios
  edge1: 
    host: 192.168.1.198
    device_type: cisco_ios
  edge2:
    host: 192.168.1.199
    device_type: cisco_ios
  new_switch:                     # 👈 Add new device
    host: 192.168.1.200
    device_type: cisco_ios
```

### Test Multiple VLANs

Create multiple target files:

```bash
# Create specific test scenarios
cp inventory/targets.yml inventory/targets-vlan20.yml
cp inventory/targets.yml inventory/targets-vlan30.yml

# Edit each with different test_vlan values
```

## 🆘 Quick Troubleshooting

### "Connection Failed" Errors
```bash
# Test SSH manually
ssh your_username@192.168.1.198

# Check device IP is correct
ping 192.168.1.198
```

### "VLAN Does Not Exist" Errors
```cisco
! On the device, create the test VLAN
configure terminal
vlan 20
 name TEST_VLAN
exit
```

### "Interface Not Found" Errors  
```cisco
! Check available interfaces
show ip interface brief
show interface status
```

## 🎯 Next Steps

Once your basic setup works:

1. **📅 Schedule Regular Tests**: Set up daily/weekly automated runs
2. **🔄 Test Different Scenarios**: Try different VLANs and interfaces  
3. **📊 Monitor Trends**: Review reports for patterns
4. **🛡️ Add More Safety**: Configure additional rollback mechanisms
5. **📈 Scale Up**: Add more devices and test scenarios

## 💡 Pro Tips

- **Start Simple**: Test with one device first, then add more
- **Use Safe VLANs**: Pick VLANs that won't disrupt your lab
- **Test Locally First**: Run `python tests/test_vlan_e2e.py --validate-only` before GitHub Actions
- **Check Logs**: Always review the detailed logs when things fail
- **Document Changes**: Keep notes about what you're testing and why

## 🎉 You're Ready!

Your network CI/CD pipeline is now set up and ready to help you:

- **Test changes safely** before applying to production
- **Catch issues early** with automated validation  
- **Build confidence** in your network modifications
- **Learn systematically** about network automation

**Happy automating!** 🚀

---

*Need help? Check the [detailed setup guide](CI-CD-SETUP.md) or review the troubleshooting section.*
