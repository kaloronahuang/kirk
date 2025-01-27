
# Add Docker's official GPG key:
sudo apt-get update

sudo apt-get install ca-certificates curl zip unzip -y
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

# Add the repository to Apt sources:
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update

sudo apt-get install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin docker-compose -y

# QEMU;

sudo apt install qemu-system python3.11-venv -y

# kirk;

git clone https://github.com/kaloronahuang/kirk.git
cd kirk
git checkout kgym/mass-ltp-exp

sudo docker build -f ./ltp-builder.Dockerfile -t kaloronahuang/ltp-builder .

python3 -m venv .venv

# activate virtualenv
source .venv/bin/activate

# SSH support
pip install asyncssh msgpack psutil
